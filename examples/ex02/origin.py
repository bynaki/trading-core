"""여러 파생 요청이 공유할 이름 데이터를 생성하는 원천 제너레이터 예제.

``NamingAllReq``를 ``@generator``에 등록하고 꽃·개·고양이 이름을 모두 담은
``NamingAllData``를 생성한다. 종류별 제너레이터를 각각 실행하는 대신 하나의
넓은 원천 모델을 만들고, 파생 단계가 필요한 필드만 선택하여 재사용하게 한다.

요청의 ``count``는 심볼별 발행 개수가 아니라 원천 전체의 발행 개수다. 원천은
정렬한 구독 심볼을 순환하며 1초마다 데이터를 발행한다. 구독 심볼의 합집합이
바뀌면 ``Domain``이 제너레이터를 새 심볼 목록으로 다시 시작할 수 있다.

``NamingAllContext``는 요청을 content ID로 보관하여 동일 컨텍스트의 중복 생성을
막는다. (의도한 대로다. 중복 생성하는지 확인하기 위해서다.) 지막 구독자가 사라지면
``@naming.close``가 요청을 분리하여 컨텍스트의
수명 주기를 마무리한다. 이 예제는 하나 이상의 심볼이 전달된다고 가정한다.
"""

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
