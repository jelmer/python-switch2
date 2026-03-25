"""API client for the Switch2 energy portal."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup, Tag

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://my.switch2.co.uk"
LOGIN_URL = f"{BASE_URL}/Login"
METER_HISTORY_URL = f"{BASE_URL}/MeterReadings/History"
BILL_HISTORY_URL = f"{BASE_URL}/Credit/BillHistory"


class Switch2AuthError(Exception):
    """Raised when authentication fails."""


class Switch2ConnectionError(Exception):
    """Raised when a connection error occurs."""


@dataclass
class CustomerInfo:
    """Customer information from the Switch2 portal."""

    name: str
    account_number: str
    address: str


@dataclass
class MeterReading:
    """A single meter reading."""

    date: datetime
    amount: float
    unit: str
    reading_type: str


@dataclass
class Bill:
    """A single bill."""

    date: datetime
    amount: float
    detail_url: str


@dataclass
class BillCharge:
    """A single line item on a bill."""

    description: str
    units: str
    charge: float


@dataclass
class BillDetail:
    """Detailed breakdown of a bill."""

    invoice_number: str
    date_of_issue: datetime
    period_from: datetime
    period_to: datetime
    consumption_charges: list[BillCharge]
    other_charges: list[BillCharge]
    total_excl_vat: float
    vat: float
    total: float
    previous_balance: float
    payments_received: float
    balance: float
    download_url: str


@dataclass
class AccountBalance:
    """Current account balance from the Switch2 portal."""

    balance: float
    last_updated: datetime


@dataclass
class Switch2Data:
    """All data fetched from the Switch2 portal."""

    customer: CustomerInfo
    readings: list[MeterReading]
    registers: dict[str, str]  # register_id -> register_name
    bills: list[Bill]
    account_balance: AccountBalance | None


def _get_attr(tag: Tag, attr: str, default: str = "") -> str:
    """Get a string attribute from a BeautifulSoup tag, handling list values."""
    value = tag.get(attr, default)
    if isinstance(value, list):
        return str(value[0]) if value else default
    return str(value) if value is not None else default


class Switch2ApiClient:
    """Client to interact with the Switch2 web portal."""

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def authenticate(self) -> tuple[CustomerInfo, BeautifulSoup]:
        """Log in to the Switch2 portal and return customer info and dashboard soup."""
        session = await self._ensure_session()

        try:
            # Step 1: GET the login page to get any CSRF tokens
            async with session.get(LOGIN_URL) as resp:
                if resp.status != 200:
                    raise Switch2ConnectionError(
                        f"Failed to load login page: HTTP {resp.status}"
                    )
                html = await resp.text()

            soup = BeautifulSoup(html, "html.parser")
            token_input = soup.select_one('input[name="__RequestVerificationToken"]')
            form_data: dict[str, str] = {}
            if token_input:
                form_data["__RequestVerificationToken"] = _get_attr(
                    token_input, "value"
                )

            # Step 2: POST login credentials
            form_data["UserName"] = self._email
            form_data["Password"] = self._password

            async with session.post(
                LOGIN_URL, data=form_data, allow_redirects=True
            ) as resp:
                if resp.status != 200:
                    raise Switch2ConnectionError(
                        f"Login request failed: HTTP {resp.status}"
                    )
                html = await resp.text()

            soup = BeautifulSoup(html, "html.parser")
            customer = _parse_customer_info(soup)
            if not customer.name:
                raise Switch2AuthError("Login failed: no customer info returned")

            return customer, soup

        except aiohttp.ClientError as err:
            raise Switch2ConnectionError(
                f"Connection error during login: {err}"
            ) from err

    async def fetch_bill_detail(self, bill: Bill) -> BillDetail:
        """Fetch and parse the detail page for a bill.

        The caller must be authenticated before calling this method.
        """
        if not bill.detail_url:
            raise ValueError("Bill has no detail URL")
        session = await self._ensure_session()
        try:
            async with session.get(bill.detail_url) as resp:
                if resp.status != 200:
                    raise Switch2ConnectionError(
                        f"Failed to load bill detail: HTTP {resp.status}"
                    )
                html = await resp.text()
        except aiohttp.ClientError as err:
            raise Switch2ConnectionError(
                f"Connection error fetching bill detail: {err}"
            ) from err
        return _parse_bill_detail(BeautifulSoup(html, "html.parser"))

    async def fetch_data(self) -> Switch2Data:
        """Authenticate and fetch all meter data."""
        customer, dashboard_soup = await self.authenticate()
        account_balance = _parse_account_balance(dashboard_soup)
        session = await self._ensure_session()

        try:
            # GET meter readings history page
            async with session.get(METER_HISTORY_URL) as resp:
                if resp.status != 200:
                    raise Switch2ConnectionError(
                        f"Failed to load meter history: HTTP {resp.status}"
                    )
                html = await resp.text()

            soup = BeautifulSoup(html, "html.parser")

            # Parse available registers
            registers: dict[str, str] = {}
            register_select = soup.select_one("#RegisterId")
            if register_select:
                for option in register_select.select("option"):
                    reg_id = option.get("value", "")
                    if reg_id:
                        registers[str(reg_id)] = option.text.strip()

            # Try to get all readings by POSTing with a large page size
            token_input = soup.select_one('input[name="__RequestVerificationToken"]')
            selected_register = soup.select_one("#RegisterId option[selected]")

            if token_input and selected_register:
                form_data = {
                    "__RequestVerificationToken": _get_attr(token_input, "value"),
                    "Page": "1",
                    "TotalPages": "1",
                    "RegisterId": _get_attr(selected_register, "value"),
                    "PageSize": "1000000",
                }

                async with session.post(
                    METER_HISTORY_URL, data=form_data, allow_redirects=True
                ) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = BeautifulSoup(html, "html.parser")

            readings = _parse_readings(soup)

            # Fetch bill history
            async with session.get(BILL_HISTORY_URL) as resp:
                if resp.status != 200:
                    raise Switch2ConnectionError(
                        f"Failed to load bill history: HTTP {resp.status}"
                    )
                html = await resp.text()

            bills = _parse_bills(BeautifulSoup(html, "html.parser"))

            return Switch2Data(
                customer=customer,
                readings=readings,
                registers=registers,
                bills=bills,
                account_balance=account_balance,
            )

        except aiohttp.ClientError as err:
            raise Switch2ConnectionError(
                f"Connection error fetching data: {err}"
            ) from err


def _parse_date(text: str) -> datetime:
    """Parse a date string like '27th February 2026'."""
    # Strip ordinal suffixes (1st, 2nd, 3rd, 4th, etc.)
    for suffix in ("st ", "nd ", "rd ", "th "):
        text = text.replace(suffix, " ")
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {text!r}")


def _parse_customer_info(soup: BeautifulSoup) -> CustomerInfo:
    """Extract customer info from the dashboard page."""
    name_el = soup.select_one(".customer-info-name")
    acn_el = soup.select_one(".customer-info-account-number")
    addr_el = soup.select_one(".customer-info-address")

    return CustomerInfo(
        name=name_el.text.strip() if name_el else "",
        account_number=acn_el.text.strip() if acn_el else "",
        address=addr_el.text.strip() if addr_el else "",
    )


def _parse_readings(soup: BeautifulSoup) -> list[MeterReading]:
    """Extract meter readings from the history page."""
    readings = []
    rows = soup.select(".meter-reading-history-table-data-row.desktop-layout")
    for row in rows:
        date_el = row.select_one(".meter-reading-history-table-data-date-row-item")
        amount_el = row.select_one(".meter-reading-history-table-data-amount-row-item")
        type_el = row.select_one(".meter-reading-history-table-data-type-row-item")
        if date_el and amount_el:
            try:
                date = _parse_date(date_el.text.strip())
                # Parse amount and unit (e.g. "8551 kWh" -> 8551, "kWh")
                amount_parts = amount_el.text.strip().split()
                amount = float(amount_parts[0])
                unit = amount_parts[1] if len(amount_parts) > 1 else ""
                reading_type = type_el.text.strip() if type_el else ""
                readings.append(
                    MeterReading(
                        date=date,
                        amount=amount,
                        unit=unit,
                        reading_type=reading_type,
                    )
                )
            except (ValueError, TypeError) as err:
                _LOGGER.debug("Failed to parse meter reading row: %s", err)

    return readings


def _parse_bills(soup: BeautifulSoup) -> list[Bill]:
    """Extract bills from the bill history page."""
    bills = []
    rows = soup.select(".bill-history-table-data-row")
    for row in rows:
        date_el = row.select_one(".bill-history-table-data-row-text-item")
        amount_el = row.select_one(
            ".bill-history-table-data-row-item-right"
            ".bill-history-table-data-row-text-item"
        )
        link_el = row.select_one("a.bill-history-view-bill-button")
        if date_el and amount_el:
            try:
                date = _parse_date(date_el.text.strip())
                # Parse amount (e.g. "£172.26" -> 172.26)
                amount_text = amount_el.text.strip().lstrip("£").replace(",", "")
                amount = float(amount_text)
                detail_url = ""
                if link_el:
                    href = _get_attr(link_el, "href")
                    detail_url = f"{BASE_URL}{href}" if href else ""
                bills.append(Bill(date=date, amount=amount, detail_url=detail_url))
            except (ValueError, TypeError) as err:
                _LOGGER.debug("Failed to parse bill row: %s", err)

    return bills


def _parse_currency(text: str) -> float:
    """Parse a currency string like '£172.26' or '-£205.13'."""
    text = text.strip()
    negative = text.startswith("-")
    text = text.lstrip("-").lstrip("£").lstrip("\xa3").replace(",", "")
    value = float(text)
    return -value if negative else value


def _parse_account_balance(soup: BeautifulSoup) -> AccountBalance | None:
    """Extract the current account balance from the dashboard page."""
    amount_el = soup.select_one(".dashboard-credit-amount-desktop")
    if not amount_el:
        return None
    balance = _parse_currency(amount_el.text)
    updated_el = soup.select_one(".dashboard-credit-lastUpdated")
    if not updated_el:
        return None
    updated_text = updated_el.text.strip()
    # Text is like "Last updated 27/02/2026 10:13"
    if updated_text.lower().startswith("last updated"):
        updated_text = updated_text[len("last updated") :].strip()
    last_updated = datetime.strptime(updated_text, "%d/%m/%Y %H:%M")
    return AccountBalance(balance=balance, last_updated=last_updated)


def _parse_bill_charges(
    soup: BeautifulSoup, container_selector: str
) -> list[BillCharge]:
    """Extract charge line items from desktop-layout rows."""
    charges: list[BillCharge] = []
    rows = soup.select(f"{container_selector} .bill-table-row-desktop .bill-table-row")
    for row in rows:
        desc_el = row.select_one(".bill-table-row-item-left")
        units_el = row.select_one(".bill-table-row-item")
        charge_el = row.select_one(".bill-table-row-item-right")
        if desc_el and charge_el:
            charges.append(
                BillCharge(
                    description=desc_el.text.strip(),
                    units=units_el.text.strip() if units_el else "",
                    charge=_parse_currency(charge_el.text),
                )
            )
    return charges


def _parse_bill_detail(soup: BeautifulSoup) -> BillDetail:
    """Extract bill detail from the bill detail page."""
    # Header: invoice number and date of issue
    header_rows = soup.select(".bill-header-row")
    invoice_number = ""
    date_of_issue_text = ""
    for row in header_rows:
        label_el = row.select_one(".bill-header-row-item")
        value_el = row.select_one(".bill-header-row-item-right")
        if label_el and value_el:
            label = label_el.text.strip().rstrip(":")
            if label == "Invoice Number":
                invoice_number = value_el.text.strip()
            elif label == "Date of issue":
                date_of_issue_text = value_el.text.strip()

    date_of_issue = _parse_date(date_of_issue_text)

    # Period: from/to dates
    from_el = soup.select_one(".bill-table-row-item-left")
    to_el = soup.select_one(".bill-table-row-item-dateto")
    period_from_text = ""
    period_to_text = ""
    if from_el:
        # Text is like "From: 27th January 2026"
        period_from_text = from_el.text.strip()
        if period_from_text.lower().startswith("from:"):
            period_from_text = period_from_text[5:].strip()
    if to_el:
        period_to_text = to_el.text.strip()
        if period_to_text.lower().startswith("to:"):
            period_to_text = period_to_text[3:].strip()

    period_from = _parse_date(period_from_text)
    period_to = _parse_date(period_to_text)

    # Consumption charges (desktop layout rows within BillItemsContainer)
    consumption_charges = _parse_bill_charges(
        soup, "#BillItemsContainer > .bill-table-row:first-of-type"
    )
    # If the CSS child selector doesn't match, fall back to looking at
    # desktop rows that come before .other-charges-table-row
    if not consumption_charges:
        items_container = soup.select_one("#BillItemsContainer")
        if items_container:
            consumption_rows: list[Tag] = []
            for child in items_container.children:
                if not isinstance(child, Tag):
                    continue
                if "other-charges-table-row" in child.get("class", []):
                    break
                desktop = child.select_one(".bill-table-row-desktop .bill-table-row")
                if desktop:
                    consumption_rows.append(desktop)
                elif "bill-table-row-desktop" in child.get("class", []):
                    inner = child.select_one(".bill-table-row")
                    if inner:
                        consumption_rows.append(inner)
            for row in consumption_rows:
                desc_el = row.select_one(".bill-table-row-item-left")
                units_el = row.select_one(".bill-table-row-item")
                charge_el = row.select_one(".bill-table-row-item-right")
                if desc_el and charge_el:
                    consumption_charges.append(
                        BillCharge(
                            description=desc_el.text.strip(),
                            units=(units_el.text.strip() if units_el else ""),
                            charge=_parse_currency(charge_el.text),
                        )
                    )

    # Other charges
    other_charges: list[BillCharge] = []
    other_header = soup.select_one(".other-charges-table-row")
    if other_header:
        sibling = other_header.next_sibling
        while sibling:
            if isinstance(sibling, Tag):
                if "bill-table-row-desktop" in sibling.get("class", []):
                    charge_row = sibling.select_one(".bill-table-row")
                    if charge_row:
                        desc_el = charge_row.select_one(".bill-table-row-item-left")
                        units_el = charge_row.select_one(".bill-table-row-item")
                        charge_el = charge_row.select_one(".bill-table-row-item-right")
                        if desc_el and charge_el:
                            other_charges.append(
                                BillCharge(
                                    description=desc_el.text.strip(),
                                    units=(units_el.text.strip() if units_el else ""),
                                    charge=_parse_currency(charge_el.text),
                                )
                            )
                elif "bill-table-row-narrow" not in sibling.get("class", []):
                    break
            sibling = sibling.next_sibling

    # Totals
    totals_container = soup.select_one("#BillTotalsCollapsibleContent")
    total_excl_vat = 0.0
    vat = 0.0
    total_rows = (
        totals_container.select(".bill-total-table-row") if totals_container else []
    )
    for row in total_rows:
        label_el = row.select_one(".bill-total-table-row-item-left")
        value_el = row.select_one(".bill-total-table-row-item-right")
        if label_el and value_el:
            label = label_el.text.strip()
            if label.startswith("Total charges excluding VAT"):
                total_excl_vat = _parse_currency(value_el.text)
            elif label.startswith("VAT"):
                vat = _parse_currency(value_el.text)

    # Bill total from the collapsible header
    total = 0.0
    total_header = soup.select_one(
        "#BillTotalsContainer > .collapsible-header .bill-total-table-row-item-right"
    )
    if total_header:
        total = _parse_currency(total_header.text)

    # Account balance
    balance_container = soup.select_one("#AccountBalanceCollapsibleContent")
    previous_balance = 0.0
    payments_received = 0.0
    balance_rows = (
        balance_container.select(".bill-total-table-row") if balance_container else []
    )
    for row in balance_rows:
        label_el = row.select_one(".bill-total-table-row-item-left")
        value_el = row.select_one(".bill-total-table-row-item-right")
        if label_el and value_el:
            label = label_el.text.strip()
            if label == "Previous account balance":
                previous_balance = _parse_currency(value_el.text)
            elif label == "Payments received":
                payments_received = _parse_currency(value_el.text)

    balance = 0.0
    balance_header = soup.select_one(
        "#AccountBalanceContainer > .collapsible-header"
        " .bill-total-table-row-item-right"
    )
    if balance_header:
        balance = _parse_currency(balance_header.text)

    # Download URL
    download_url = ""
    download_el = soup.select_one("#DownloadBillButton")
    if download_el:
        href = _get_attr(download_el, "href")
        download_url = f"{BASE_URL}{href}" if href else ""

    return BillDetail(
        invoice_number=invoice_number,
        date_of_issue=date_of_issue,
        period_from=period_from,
        period_to=period_to,
        consumption_charges=consumption_charges,
        other_charges=other_charges,
        total_excl_vat=total_excl_vat,
        vat=vat,
        total=total,
        previous_balance=previous_balance,
        payments_received=payments_received,
        balance=balance,
        download_url=download_url,
    )
