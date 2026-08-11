import asyncio

from trading_core import Domain, cast_model

if __package__:
    from .ex04 import OHLCData, OHLCRequest
else:
    from ex04 import OHLCData, OHLCRequest


async def run_ex(domain: Domain) -> None:

    print("===== runing ex04 =====")
    print('----- OHLCRequest(quote="usd", interval="5m") -----')
    req01 = OHLCRequest(quote="usd", interval="5m")
    async with domain.request(req01, {"BTC", "ETH"}) as gen:
        count = 0
        async for data in gen:
            d = cast_model(data, OHLCData)
            print(d.model_dump_json(indent=2))
            count += 1
            if count == 10:
                break
    print('----- OHLCRequest(quote="krw", interval="1h") -----')
    req02 = OHLCRequest(quote="krw", interval="1h")
    async with domain.request(req02, {"BTC", "ETH"}) as gen:
        count = 0
        async for data in gen:
            d = cast_model(data, OHLCData)
            print(d.model_dump_json(indent=2))
            count += 1
            if count == 10:
                break
    print("===== finished ex04 =====")


async def main() -> None:
    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    asyncio.run(main())
