from trading_core import Domain

if __package__:
    from .ex03 import PriceData, PriceReq
else:
    from ex03 import PriceData, PriceReq

from asyncio import run, sleep


async def sender(data: PriceData):
    print(data.model_dump_json(indent=2))


async def run_ex(domain: Domain):
    print("===== runing ex03 =====")
    symbols: set[str] = set()
    req = PriceReq(ohlc="close")
    async with domain.stage(req, sender) as stage:
        i = 0
        for i in range(5):
            symbols.add(f"symbol{i + 1}")
            await stage.update(symbols)
            await sleep(1)
        for j in range(i, 0, -1):
            symbols.remove(f"symbol{j + 1}")
            await stage.update(symbols)
            await sleep(1)
    print("===== finished ex03 =====")


async def main():
    domain = Domain()
    await domain.start()
    await run_ex(domain)


if __name__ == "__main__":
    run(main())
