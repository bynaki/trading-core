"""여러 파생 요청이 공유하는 꽃·개·고양이 이름 원천 예제."""

from asyncio import sleep

from trading_core import DataModel, GenerateModel, initialize

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


class NamingAllReq(GenerateModel):
    """모든 이름 종류를 함께 요청하는 필드 없는 공통 원천 요청."""


class NamingAllData(DataModel):
    """한 심볼에 대응하는 세 종류의 이름과 발행 순번."""

    flower: str
    dog: str
    cat: str
    count: int


class NamingAllContext:
    """원천 요청의 유일성과 binder 재시작 횟수를 추적하는 공유 컨텍스트."""

    cxt_dict: dict[str, NamingAllReq] = {}

    def __init__(self, req: NamingAllReq) -> None:
        self.content_id = req.get_tr_content_id()
        assert not self.cxt_dict.get(req.get_tr_content_id()), (
            "중복 'content_id' 갖은 객체는 생성할수 없다. 유일해야 한다."
        )
        self.cxt_dict[self.content_id] = req
        self.count = 0

    @property
    def req_model(self) -> NamingAllReq:
        """content ID에 연결된 원천 요청을 반환한다."""

        return self.cxt_dict[self.content_id]

    def detach(self) -> None:
        """스테이지가 닫힐 때 클래스 수준 저장소에서 요청을 제거한다."""

        del self.cxt_dict[self.content_id]


@initialize
def naming(req: NamingAllReq) -> NamingAllContext:
    """공통 이름 원천이 수명 동안 재사용할 컨텍스트를 만든다."""

    return NamingAllContext(req=req)


@naming
async def _(ctx: NamingAllContext, symbols: set[str]):
    """정렬한 심볼을 순환하며 세 종류의 이름을 한 레코드로 발행한다."""

    ctx.count += 1
    print(f"!!!!!!! {ctx.count} Updating NamingAll Stage")
    symbol_list = list(symbols)
    symbol_list.sort()
    i = 0
    while True:
        symbol = symbol_list[i % len(symbol_list)]
        flower = f"{flower_names[i % len(flower_names)]}:{symbol}"
        dog = f"{dog_names[i % len(dog_names)]}:{symbol}"
        cat = f"{cat_names[i % len(cat_names)]}:{symbol}"
        yield NamingAllData(flower=flower, dog=dog, cat=cat, count=i + 1, symbol=symbol)
        i += 1
        await sleep(0.5)


@naming.detached
async def _(ctx: NamingAllContext):
    """마지막 원천 구독이 사라지면 공유 컨텍스트를 분리한다."""

    ctx.detach()
    print("******* Detached NamingAll Stage")
