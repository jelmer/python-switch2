# python-switch2

Async Python client library for the [Switch2](https://my.switch2.co.uk) energy portal.

## Installation

```sh
pip install switch2
```

## Usage

```python
import asyncio
from switch2 import Switch2ApiClient


async def main():
    async with Switch2ApiClient("you@example.com", "your-password") as client:
        data = await client.fetch_data()
        print(f"Customer: {data.customer.name}")
        if data.account_balance is not None:
            print(f"Balance: £{data.account_balance.balance}")
        for reading in data.readings:
            print(f"  {reading.date}: {reading.amount} {reading.unit}")
        for bill in data.bills:
            print(f"  {bill.date}: £{bill.amount}")
            detail = await client.fetch_bill_detail(bill)
            print(f"    invoice {detail.invoice_number}, total £{detail.total}")


asyncio.run(main())
```

All exceptions derive from `Switch2Error`. `Switch2AuthError` means the
portal rejected the credentials; `Switch2ParseError` means a page did not
look the way the parser expects, which usually means the portal changed;
`Switch2UnavailableError` means the portal failed to load data it normally
has, which tends to pass if you try again later.

`data.readings` holds the readings of the register the portal selects by
default; `data.register_readings` maps each register in `data.registers`
to its readings.

## Command line

```sh
SWITCH2_PASSWORD=... python -m switch2 you@example.com
```

prints what the portal reports. With `--dump-html DIR` it also saves every
page it fetches, which is the easiest way to capture a page the parser gets
wrong.

## License

Apache-2.0
