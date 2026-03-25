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
    client = Switch2ApiClient("you@example.com", "your-password")
    try:
        data = await client.fetch_data()
        print(f"Customer: {data.customer.name}")
        for reading in data.readings:
            print(f"  {reading.date}: {reading.amount} {reading.unit}")
        for bill in data.bills:
            print(f"  {bill.date}: £{bill.amount}")
    finally:
        await client.close()

asyncio.run(main())
```

## License

Apache-2.0
