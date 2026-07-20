from asyncio import sleep
from typing import TypedDict

from trading_core import DataModel, Receiver, RequestModel, generator

flower_names = [
    "Rose",
    "Tulip",
    "Sunflower",
    "Lily",
    "Chrysanthemum",
    "Daffodil",
    "Lavender",
    "Camellia",
    "Dandelion",
    "Hibiscus",
]

dog_names = [
    "Golden Retriever",
    "Labrador Retriever",
    "Beagle",
    "Poodle",
    "Shiba Inu",
    "Welsh Corgi",
    "Border Collie",
    "Pomeranian",
    "Maltese",
    "Jindo",
]

cat_names = [
    "Luna",
    "Oliver",
    "Leo",
    "Milo",
    "Bella",
    "Lucy",
    "Nala",
    "Simba",
    "Coco",
    "Chloe",
]


class NamingAllReq(RequestModel):
    count: int


class NamingAllData(DataModel):
    flower: str
    dog: str
    cat: str
    count: int


class NamingAllContext(TypedDict):
    req: NamingAllReq


@generator(NamingAllReq)
def naming(req: NamingAllReq) -> NamingAllContext:
    return NamingAllContext(req=req)


@naming.bind
async def _(ctx: NamingAllContext, symbols: set[str], recv: Receiver | None):
    req = ctx["req"]
    symbol_list = list(symbols)
    symbol_list.sort()
    for i in range(req.count):
        symbol = symbol_list[i % len(symbol_list)]
        flower = f"{flower_names[i % len(flower_names)]}:{symbol}"
        dog = f"{dog_names[i % len(dog_names)]}:{symbol}"
        cat = f"{cat_names[i % len(cat_names)]}:{symbol}"
        yield NamingAllData(flower=flower, dog=dog, cat=cat, count=i + 1, symbol=symbol)
        await sleep(1)


@naming.close
async def _(ctx: NamingAllContext):
    print("Closed NamingAllReq")
