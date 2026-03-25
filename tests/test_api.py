"""Tests for the Switch2 API client."""

import unittest
from datetime import datetime

from bs4 import BeautifulSoup

from switch2.api import (
    _parse_bills,
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
