import asyncio

import ex01

from trading_core import (
    Domain,
)


async def main():
    domain = Domain()
    await domain.start()
    req = ex01.CountReq(start=0)
    async with domain.request(req, {"BTC", "USDT", "ETH", "XRP"}) as gen:
        async for data in gen:
            print(data.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
