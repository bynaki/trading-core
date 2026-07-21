from asyncio import sleep

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


class NamingAllContext:
    cxt_dict: dict[str, NamingAllReq] = {}

    def __init__(self, req: NamingAllReq) -> None:
        self.content_id = req.get_tr_content_id()
        assert not self.cxt_dict.get(req.get_tr_content_id()), (
            "중복 'content_id' 갖은 객체는 생성할수 없다. 유일해야 한다."
        )
        self.cxt_dict[self.content_id] = req

    @property
    def req_model(self) -> NamingAllReq:
        return self.cxt_dict[self.content_id]

    def detach(self) -> None:
        del self.cxt_dict[self.content_id]


@generator(NamingAllReq)
def naming(req: NamingAllReq) -> NamingAllContext:
    return NamingAllContext(req=req)


@naming.bind
async def _(ctx: NamingAllContext, symbols: set[str], recv: Receiver | None):
    req = ctx.req_model
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
    ctx.detach()
    print("Detached NamingAllReq")
