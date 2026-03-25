"""Tests for the Switch2 API client."""

import unittest
from datetime import datetime

from bs4 import BeautifulSoup

from switch2.api import (
    _parse_bill_detail,
    _parse_bills,
    _parse_currency,
    _parse_customer_info,
    _parse_date,
    _parse_readings,
)


class ParseDateTests(unittest.TestCase):
    def test_ordinal_th(self) -> None:
        self.assertEqual(_parse_date("27th February 2026"), datetime(2026, 2, 27))

    def test_ordinal_st(self) -> None:
        self.assertEqual(_parse_date("1st January 2025"), datetime(2025, 1, 1))

    def test_ordinal_nd(self) -> None:
        self.assertEqual(_parse_date("2nd March 2025"), datetime(2025, 3, 2))

    def test_ordinal_rd(self) -> None:
        self.assertEqual(_parse_date("3rd April 2025"), datetime(2025, 4, 3))

    def test_abbreviated_month(self) -> None:
        self.assertEqual(_parse_date("15th Jan 2025"), datetime(2025, 1, 15))

    def test_invalid_date(self) -> None:
        with self.assertRaises(ValueError):
            _parse_date("not a date")


class ParseCustomerInfoTests(unittest.TestCase):
    def test_full_info(self) -> None:
        html = """
        <div>
            <span class="customer-info-name">John Doe</span>
            <span class="customer-info-account-number">ACC-123</span>
            <span class="customer-info-address">42 Test Lane</span>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        info = _parse_customer_info(soup)
        self.assertEqual(info.name, "John Doe")
        self.assertEqual(info.account_number, "ACC-123")
        self.assertEqual(info.address, "42 Test Lane")

    def test_missing_elements(self) -> None:
        soup = BeautifulSoup("<div></div>", "html.parser")
        info = _parse_customer_info(soup)
        self.assertEqual(info.name, "")
        self.assertEqual(info.account_number, "")
        self.assertEqual(info.address, "")


class ParseReadingsTests(unittest.TestCase):
    def test_single_reading(self) -> None:
        html = """
        <div class="meter-reading-history-table-data-row desktop-layout">
            <div class="meter-reading-history-table-data-date-row-item">
                27th February 2026
            </div>
            <div class="meter-reading-history-table-data-amount-row-item">
                8551 kWh
            </div>
            <div class="meter-reading-history-table-data-type-row-item">
                Actual
            </div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        readings = _parse_readings(soup)
        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0].date, datetime(2026, 2, 27))
        self.assertEqual(readings[0].amount, 8551.0)
        self.assertEqual(readings[0].unit, "kWh")
        self.assertEqual(readings[0].reading_type, "Actual")

    def test_no_readings(self) -> None:
        soup = BeautifulSoup("<div></div>", "html.parser")
        self.assertEqual(_parse_readings(soup), [])

    def test_amount_without_unit(self) -> None:
        html = """
        <div class="meter-reading-history-table-data-row desktop-layout">
            <div class="meter-reading-history-table-data-date-row-item">
                1st January 2025
            </div>
            <div class="meter-reading-history-table-data-amount-row-item">
                1234
            </div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        readings = _parse_readings(soup)
        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0].unit, "")
        self.assertEqual(readings[0].reading_type, "")


class ParseBillsTests(unittest.TestCase):
    def test_single_bill(self) -> None:
        bill_amount_cls = (
            "bill-history-table-data-row-item-right"
            " bill-history-table-data-row-text-item"
        )
        html = f"""
        <div class="bill-history-table-data-row">
            <div class="bill-history-table-data-row-text-item">
                15th March 2025
            </div>
            <div class="{bill_amount_cls}">£172.26</div>
            <a class="bill-history-view-bill-button"
               href="/Credit/Bill/42">View</a>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        bills = _parse_bills(soup)
        self.assertEqual(len(bills), 1)
        self.assertEqual(bills[0].date, datetime(2025, 3, 15))
        self.assertEqual(bills[0].amount, 172.26)
        self.assertEqual(bills[0].detail_url, "https://my.switch2.co.uk/Credit/Bill/42")

    def test_no_bills(self) -> None:
        soup = BeautifulSoup("<div></div>", "html.parser")
        self.assertEqual(_parse_bills(soup), [])

    def test_bill_without_link(self) -> None:
        bill_amount_cls = (
            "bill-history-table-data-row-item-right"
            " bill-history-table-data-row-text-item"
        )
        html = f"""
        <div class="bill-history-table-data-row">
            <div class="bill-history-table-data-row-text-item">
                1st January 2025
            </div>
            <div class="{bill_amount_cls}">£50.00</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        bills = _parse_bills(soup)
        self.assertEqual(len(bills), 1)
        self.assertEqual(bills[0].detail_url, "")


class ParseCurrencyTests(unittest.TestCase):
    def test_pounds(self) -> None:
        self.assertEqual(_parse_currency("£172.26"), 172.26)

    def test_negative(self) -> None:
        self.assertEqual(_parse_currency("-£205.13"), -205.13)

    def test_with_comma(self) -> None:
        self.assertEqual(_parse_currency("£1,234.56"), 1234.56)

    def test_html_entity(self) -> None:
        self.assertEqual(_parse_currency("\xa3105.97"), 105.97)


class ParseBillDetailTests(unittest.TestCase):
    BILL_DETAIL_HTML = """\
<div class="bill-container border-color-2">
  <div class="bill-header-container border-color-2 font-large">
    <div class="bill-header-row fg-color-2">
      <div class="bill-header-row-item">Invoice Number:</div>
      <div class="bill-header-row-item-right fg-color-4">
        0642001470
      </div>
      <div class="clear-fix"></div>
    </div>
    <div class="bill-header-row fg-color-2">
      <div class="bill-header-row-item">Date of issue:</div>
      <div class="bill-header-row-item-right fg-color-4">
        27th February 2026
      </div>
      <div class="clear-fix"></div>
    </div>
  </div>

  <div class="bill-table-row bg-color-1 fg-color-1">
    <div class="bill-table-row-item-left">
      From:&nbsp;27th January 2026
    </div>
    <div class="bill-table-row-item bill-table-row-item-dateto">
      To: 26th February 2026
    </div>
    <div class="clear-fix"></div>
  </div>

  <div id="BillItemsContainer">
    <div class="bill-table-row fg-color-2 font-bold">
      <div class="bill-table-row-item-left">Consumption charges</div>
    </div>
    <div class="bill-table-row-desktop">
      <div class="bill-table-row bg-color-6 fg-color-4 font-bold">
        <div class="bill-table-row-item-left">Heat</div>
        <div class="bill-table-row-item">623 kWh</div>
        <div class="bill-table-row-item-right">&#163;105.97</div>
        <div class="clear-fix"></div>
      </div>
    </div>
    <div class="bill-table-row-narrow"></div>

    <div class="other-charges-table-row fg-color-2 font-bold">
      <div class="other-charges-row-item">Other charges</div>
    </div>
    <div class="bill-table-row-desktop">
      <div class="bill-table-row bg-color-6 fg-color-4 font-bold">
        <div class="bill-table-row-item-left">Heat Standing Charge</div>
        <div class="bill-table-row-item">31.00 days</div>
        <div class="bill-table-row-item-right">&#163;23.21</div>
        <div class="clear-fix"></div>
      </div>
    </div>
    <div class="bill-table-row-narrow"></div>
    <div class="bill-table-row-desktop">
      <div class="bill-table-row bg-color-6 fg-color-4 font-bold">
        <div class="bill-table-row-item-left">
          Admin Standing Charge
        </div>
        <div class="bill-table-row-item">31.00 days</div>
        <div class="bill-table-row-item-right">&#163;34.88</div>
        <div class="clear-fix"></div>
      </div>
    </div>
    <div class="bill-table-row-narrow"></div>
  </div>

  <div id="BillTotalsContainer" class="collapsible-container">
    <div class="collapsible-header bill-total-table-row bg-color-4">
      <div class="bill-total-table-row-item-left">Bill total</div>
      <div class="bill-total-table-row-item-right">
        &#163;172.26
      </div>
    </div>
    <div id="BillTotalsCollapsibleContent" class="collapsible">
      <div class="bill-total-table-row bg-color-3 fg-color-4">
        <div class="bill-total-table-row-item-left">
          VAT @ 5% on &#163;164.06
        </div>
        <div class="bill-total-table-row-item-right">£8.20</div>
      </div>
      <div class="bill-total-table-row bg-color-3 fg-color-4">
        <div class="bill-total-table-row-item-left">
          Total charges excluding VAT
        </div>
        <div class="bill-total-table-row-item-right">£164.06</div>
      </div>
    </div>
  </div>

  <div id="AccountBalanceContainer" class="collapsible-container">
    <div class="collapsible-header bill-total-table-row bg-color-5">
      <div class="bill-total-table-row-item-left">
        Balance as of 27th February 2026
      </div>
      <div class="bill-total-table-row-item-right">
        &#163;172.26
      </div>
    </div>
    <div id="AccountBalanceCollapsibleContent" class="collapsible">
      <div class="bill-total-table-row bg-color-6 fg-color-4">
        <div class="bill-total-table-row-item-left">
          Previous account balance
        </div>
        <div class="bill-total-table-row-item-right">£205.13</div>
      </div>
      <div class="bill-total-table-row bg-color-6 fg-color-4">
        <div class="bill-total-table-row-item-left">
          Payments received
        </div>
        <div class="bill-total-table-row-item-right">-£205.13</div>
      </div>
    </div>
  </div>

  <a id="DownloadBillButton"
     href="/Credit/Bill/Download/2289896"
     class="wizard-button">
    <span>Download this bill</span>
  </a>
</div>
"""

    def test_invoice_number(self) -> None:
        soup = BeautifulSoup(self.BILL_DETAIL_HTML, "html.parser")
        detail = _parse_bill_detail(soup)
        self.assertEqual(detail.invoice_number, "0642001470")

    def test_date_of_issue(self) -> None:
        soup = BeautifulSoup(self.BILL_DETAIL_HTML, "html.parser")
        detail = _parse_bill_detail(soup)
        self.assertEqual(detail.date_of_issue, datetime(2026, 2, 27))

    def test_period(self) -> None:
        soup = BeautifulSoup(self.BILL_DETAIL_HTML, "html.parser")
        detail = _parse_bill_detail(soup)
        self.assertEqual(detail.period_from, datetime(2026, 1, 27))
        self.assertEqual(detail.period_to, datetime(2026, 2, 26))

    def test_consumption_charges(self) -> None:
        soup = BeautifulSoup(self.BILL_DETAIL_HTML, "html.parser")
        detail = _parse_bill_detail(soup)
        self.assertEqual(len(detail.consumption_charges), 1)
        self.assertEqual(detail.consumption_charges[0].description, "Heat")
        self.assertEqual(detail.consumption_charges[0].units, "623 kWh")
        self.assertEqual(detail.consumption_charges[0].charge, 105.97)

    def test_other_charges(self) -> None:
        soup = BeautifulSoup(self.BILL_DETAIL_HTML, "html.parser")
        detail = _parse_bill_detail(soup)
        self.assertEqual(len(detail.other_charges), 2)
        self.assertEqual(
            detail.other_charges[0].description,
            "Heat Standing Charge",
        )
        self.assertEqual(detail.other_charges[0].units, "31.00 days")
        self.assertEqual(detail.other_charges[0].charge, 23.21)
        self.assertEqual(
            detail.other_charges[1].description,
            "Admin Standing Charge",
        )
        self.assertEqual(detail.other_charges[1].charge, 34.88)

    def test_totals(self) -> None:
        soup = BeautifulSoup(self.BILL_DETAIL_HTML, "html.parser")
        detail = _parse_bill_detail(soup)
        self.assertEqual(detail.total_excl_vat, 164.06)
        self.assertEqual(detail.vat, 8.20)
        self.assertEqual(detail.total, 172.26)

    def test_account_balance(self) -> None:
        soup = BeautifulSoup(self.BILL_DETAIL_HTML, "html.parser")
        detail = _parse_bill_detail(soup)
        self.assertEqual(detail.previous_balance, 205.13)
        self.assertEqual(detail.payments_received, -205.13)
        self.assertEqual(detail.balance, 172.26)

    def test_download_url(self) -> None:
        soup = BeautifulSoup(self.BILL_DETAIL_HTML, "html.parser")
        detail = _parse_bill_detail(soup)
        self.assertEqual(
            detail.download_url,
            "https://my.switch2.co.uk/Credit/Bill/Download/2289896",
        )
