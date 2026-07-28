import asyncio

from trading_core import Domain, cast_model

if __package__:
    from .ex01 import CountData, CountReq
else:
    from ex01 import CountData, CountReq


async def run_ex(domain: Domain):
    print("===== runing ex01 =====")
    req01 = CountReq(start=1)
    async with domain.request(req01, {"BTC", "USDT", "ETH", "XRP"}) as gen:
        async for data in gen:
            d = cast_model(data, CountData)
            print(d.model_dump_json(indent=2))
            if d.count == 10:
                break
    print("===== finished ex01 =====")


async def main():
    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    asyncio.run(main())
