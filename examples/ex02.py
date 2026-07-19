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


class NamingContext(TypedDict):
    req: NamingAllReq


@generator(NamingAllReq)
def naming(req: NamingAllReq) -> NamingContext:
    return NamingContext(req=req)


@naming.bind
async def _(ctx: NamingContext, symbols: set[str], recv: Receiver | None):
    req = ctx["req"]
    symbol_list = list(symbols)
    symbol_list.sort()
    for i in range(req.count):
        symbol = symbol_list[i % len(symbol_list)]
        flower = f"{flower_names[i]}:{symbol}"
        dog = f"{dog_names[i]}:{symbol}"
        cat = f"{cat_names[i]}:{symbol}"
        yield NamingAllData(flower=flower, dog=dog, cat=cat, symbol=symbol)
        await sleep(1)


@naming.close
async def _(ctx: NamingContext):
    print("Closed NamingAllReq")
