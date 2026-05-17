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

## License

Apache-2.0
