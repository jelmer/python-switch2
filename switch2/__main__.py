"""Print what the Switch2 portal reports for an account.

Usage: python -m switch2 [--dump-html DIR] EMAIL

The password is read from $SWITCH2_PASSWORD, or prompted for.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from .api import Switch2ApiClient


def _page_saver(directory: Path) -> Callable[[str, str], None]:
    counts: dict[str, int] = {}

    def save(url: str, html: str) -> None:
        name = urlparse(url).path.strip("/").replace("/", "_") or "index"
        counts[name] = counts.get(name, 0) + 1
        path = directory / f"{name}-{counts[name]}.html"
        path.write_text(html)
        print(f"Saved {url} to {path}")

    return save


async def _run(email: str, password: str, dump_dir: Path | None) -> None:
    on_page: Callable[[str, str], None] | None = None
    if dump_dir is not None:
        dump_dir.mkdir(parents=True, exist_ok=True)
        on_page = _page_saver(dump_dir)

    async with Switch2ApiClient(email, password, on_page=on_page) as client:
        data = await client.fetch_data()
        print(f"Customer: {data.customer}")
        print(f"Account balance: {data.account_balance}")
        for register_id, name in data.registers.items():
            readings = data.register_readings.get(register_id, [])
            print(f"Register {register_id} ({name}): {len(readings)} readings")
            for reading in readings[:3]:
                print(f"  {reading}")
        print(f"Bills: {len(data.bills)}")
        if data.bills:
            print(f"Latest bill: {data.bills[0]}")
            detail = await client.fetch_bill_detail(data.bills[0])
            for charge in detail.consumption_charges:
                print(f"  consumption: {charge}")
            for charge in detail.other_charges:
                print(f"  other: {charge}")
            print(f"  total excl. VAT: {detail.total_excl_vat}, VAT: {detail.vat}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m switch2")
    parser.add_argument("email")
    parser.add_argument(
        "--dump-html",
        type=Path,
        metavar="DIR",
        help="save every page fetched to DIR",
    )
    args = parser.parse_args()
    password = os.environ.get("SWITCH2_PASSWORD") or getpass.getpass()
    asyncio.run(_run(args.email, password, args.dump_html))


if __name__ == "__main__":
    main()
