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
class Switch2Data:
    """All data fetched from the Switch2 portal."""

    customer: CustomerInfo
    readings: list[MeterReading]
    registers: dict[str, str]  # register_id -> register_name
    bills: list[Bill]


def _get_attr(tag: Tag, attr: str, default: str = "") -> str:
    """Get a string attribute from a BeautifulSoup tag, handling list values."""
    value = tag.get(attr, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value


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

    async def authenticate(self) -> CustomerInfo:
        """Log in to the Switch2 portal and return customer info."""
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

            return customer

        except aiohttp.ClientError as err:
            raise Switch2ConnectionError(
                f"Connection error during login: {err}"
            ) from err

    async def fetch_data(self) -> Switch2Data:
        """Authenticate and fetch all meter data."""
        customer = await self.authenticate()
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
