"""심볼 표기가 서로 다른 두 거래소를 하나의 OHLC 모델로 정규화하는 예제.

`require` 콜백이 상위 요청뿐 아니라 심볼 집합까지 변환한다. 소비자는 `"BTC"` 같은
기초 자산만 요청하고, 원천에는 `"BTC/USD"` · `"BTC/KRW"`처럼 거래소 표기로 바뀌어
전달된다. 어떤 원천을 쓸지도 `OHLCRequest.quote` 값에 따라 달라진다.
"""

import re
from asyncio import sleep
from typing import Literal

from trading_core import DataModel, DependentModel, GenerateModel, initialize
from trading_core.model import Receiver, cast_model

_SYMBOL_PATTERN = re.compile(r"^([A-Z0-9]+)/([A-Z0-9]+)$")


def base_of(symbol: str) -> str:
    """`"BTC/USDT"`처럼 `기초/견적` 형식인 심볼에서 기초 자산(`"BTC"`)만 뽑아낸다."""
    matched = _SYMBOL_PATTERN.match(symbol)
    if matched is None:
        raise ValueError(f"'{symbol}'은(는) '기초/견적' 형식의 심볼이 아니다")
    return matched.group(1)


class BinanceRequest(GenerateModel):
    """USD 마켓 캔들을 요청하는 원천 요청. `interval`이 봉의 주기다."""

    interval: Literal["1m", "5m", "1h"]


class BinanceData(DataModel):
    """줄임말 필드를 쓰는 USD 마켓 캔들.

    `op`: 시가, `hi`: 고가, `lo`: 저가, `cl`: 종가, `vol`: 거래량이며 `symbol`은
    `"BTC/USD"`처럼 거래소 표기를 그대로 쓴다.
    """

    op: float
    hi: float
    lo: float
    cl: float
    vol: float


# 주기별로 10개의 캔들을 담은 USD 마켓 모의 데이터. binder가 순환하며 발행한다.
MOCK_BTC_USD: dict[str, list[BinanceData]] = {
    "1m": [
        BinanceData(symbol="BTC/USD", op=68120.5, hi=68240.0, lo=68090.1, cl=68205.3, vol=12.480),
        BinanceData(symbol="BTC/USD", op=68205.3, hi=68310.7, lo=68180.0, cl=68295.9, vol=9.732),
        BinanceData(symbol="BTC/USD", op=68295.9, hi=68300.2, lo=68050.4, cl=68110.6, vol=21.005),
        BinanceData(symbol="BTC/USD", op=68110.6, hi=68175.8, lo=67980.0, cl=68020.2, vol=15.617),
        BinanceData(symbol="BTC/USD", op=68020.2, hi=68140.9, lo=67995.5, cl=68132.4, vol=7.884),
        BinanceData(symbol="BTC/USD", op=68132.4, hi=68260.3, lo=68115.7, cl=68248.1, vol=10.336),
        BinanceData(symbol="BTC/USD", op=68248.1, hi=68402.6, lo=68230.9, cl=68388.5, vol=18.129),
        BinanceData(symbol="BTC/USD", op=68388.5, hi=68420.0, lo=68301.2, cl=68325.7, vol=13.470),
        BinanceData(symbol="BTC/USD", op=68325.7, hi=68350.4, lo=68190.6, cl=68212.9, vol=16.955),
        BinanceData(symbol="BTC/USD", op=68212.9, hi=68298.8, lo=68201.0, cl=68277.4, vol=8.612),
    ],
    "5m": [
        BinanceData(symbol="BTC/USD", op=67980.0, hi=68310.0, lo=67940.2, cl=68205.3, vol=58.420),
        BinanceData(symbol="BTC/USD", op=68205.3, hi=68460.8, lo=68150.0, cl=68402.6, vol=47.135),
        BinanceData(symbol="BTC/USD", op=68402.6, hi=68520.4, lo=68280.5, cl=68318.9, vol=63.907),
        BinanceData(symbol="BTC/USD", op=68318.9, hi=68390.0, lo=67910.3, cl=67985.4, vol=88.274),
        BinanceData(symbol="BTC/USD", op=67985.4, hi=68120.6, lo=67840.0, cl=68075.1, vol=71.652),
        BinanceData(symbol="BTC/USD", op=68075.1, hi=68340.9, lo=68040.7, cl=68296.8, vol=55.318),
        BinanceData(symbol="BTC/USD", op=68296.8, hi=68610.2, lo=68270.4, cl=68574.5, vol=94.081),
        BinanceData(symbol="BTC/USD", op=68574.5, hi=68680.0, lo=68420.1, cl=68465.3, vol=66.723),
        BinanceData(symbol="BTC/USD", op=68465.3, hi=68512.7, lo=68190.9, cl=68240.6, vol=59.446),
        BinanceData(symbol="BTC/USD", op=68240.6, hi=68398.5, lo=68205.0, cl=68371.2, vol=48.960),
    ],
    "1h": [
        BinanceData(symbol="BTC/USD", op=67420.0, hi=68180.5, lo=67310.2, cl=68052.7, vol=612.35),
        BinanceData(symbol="BTC/USD", op=68052.7, hi=68740.9, lo=67980.4, cl=68610.3, vol=548.91),
        BinanceData(symbol="BTC/USD", op=68610.3, hi=68920.0, lo=68350.8, cl=68455.6, vol=703.24),
        BinanceData(symbol="BTC/USD", op=68455.6, hi=68560.1, lo=67640.3, cl=67810.9, vol=869.57),
        BinanceData(symbol="BTC/USD", op=67810.9, hi=68240.7, lo=67520.0, cl=68165.4, vol=745.12),
        BinanceData(symbol="BTC/USD", op=68165.4, hi=68880.3, lo=68090.6, cl=68792.1, vol=655.48),
        BinanceData(symbol="BTC/USD", op=68792.1, hi=69340.5, lo=68710.0, cl=69205.7, vol=921.36),
        BinanceData(symbol="BTC/USD", op=69205.7, hi=69420.8, lo=68840.2, cl=68965.4, vol=812.09),
        BinanceData(symbol="BTC/USD", op=68965.4, hi=69080.0, lo=68410.5, cl=68520.8, vol=690.73),
        BinanceData(symbol="BTC/USD", op=68520.8, hi=68990.4, lo=68470.1, cl=68874.2, vol=578.60),
    ],
}

MOCK_ETH_USD: dict[str, list[BinanceData]] = {
    "1m": [
        BinanceData(symbol="ETH/USD", op=3210.44, hi=3225.10, lo=3204.80, cl=3221.75, vol=140.22),
        BinanceData(symbol="ETH/USD", op=3221.75, hi=3238.60, lo=3219.02, cl=3230.11, vol=98.451),
        BinanceData(symbol="ETH/USD", op=3230.11, hi=3231.90, lo=3198.33, cl=3205.67, vol=175.30),
        BinanceData(symbol="ETH/USD", op=3205.67, hi=3212.45, lo=3190.10, cl=3196.88, vol=132.77),
        BinanceData(symbol="ETH/USD", op=3196.88, hi=3218.00, lo=3195.20, cl=3214.53, vol=110.90),
        BinanceData(symbol="ETH/USD", op=3214.53, hi=3240.85, lo=3212.90, cl=3236.40, vol=155.03),
        BinanceData(symbol="ETH/USD", op=3236.40, hi=3251.22, lo=3233.15, cl=3244.97, vol=121.66),
        BinanceData(symbol="ETH/USD", op=3244.97, hi=3248.30, lo=3220.05, cl=3225.18, vol=143.51),
        BinanceData(symbol="ETH/USD", op=3225.18, hi=3229.70, lo=3202.44, cl=3208.62, vol=168.24),
        BinanceData(symbol="ETH/USD", op=3208.62, hi=3231.55, lo=3206.90, cl=3228.31, vol=127.48),
    ],
    "5m": [
        BinanceData(symbol="ETH/USD", op=3190.10, hi=3226.40, lo=3186.55, cl=3221.75, vol=620.18),
        BinanceData(symbol="ETH/USD", op=3221.75, hi=3248.90, lo=3215.30, cl=3240.62, vol=533.47),
        BinanceData(symbol="ETH/USD", op=3240.62, hi=3255.10, lo=3228.44, cl=3234.05, vol=701.92),
        BinanceData(symbol="ETH/USD", op=3234.05, hi=3238.70, lo=3192.16, cl=3200.88, vol=845.33),
        BinanceData(symbol="ETH/USD", op=3200.88, hi=3218.55, lo=3188.02, cl=3213.40, vol=762.55),
        BinanceData(symbol="ETH/USD", op=3213.40, hi=3246.80, lo=3209.75, cl=3242.19, vol=588.04),
        BinanceData(symbol="ETH/USD", op=3242.19, hi=3278.35, lo=3238.90, cl=3271.66, vol=934.71),
        BinanceData(symbol="ETH/USD", op=3271.66, hi=3284.00, lo=3252.10, cl=3258.93, vol=677.28),
        BinanceData(symbol="ETH/USD", op=3258.93, hi=3264.45, lo=3226.70, cl=3232.51, vol=604.86),
        BinanceData(symbol="ETH/USD", op=3232.51, hi=3250.20, lo=3229.08, cl=3247.34, vol=512.39),
    ],
    "1h": [
        BinanceData(symbol="ETH/USD", op=3152.60, hi=3208.44, lo=3140.15, cl=3196.82, vol=6420.1),
        BinanceData(symbol="ETH/USD", op=3196.82, hi=3262.30, lo=3190.05, cl=3255.71, vol=5837.4),
        BinanceData(symbol="ETH/USD", op=3255.71, hi=3288.90, lo=3241.60, cl=3249.03, vol=7104.6),
        BinanceData(symbol="ETH/USD", op=3249.03, hi=3260.15, lo=3172.80, cl=3185.46, vol=8930.2),
        BinanceData(symbol="ETH/USD", op=3185.46, hi=3228.70, lo=3160.35, cl=3220.94, vol=7561.8),
        BinanceData(symbol="ETH/USD", op=3220.94, hi=3290.60, lo=3214.20, cl=3283.15, vol=6295.0),
        BinanceData(symbol="ETH/USD", op=3283.15, hi=3345.80, lo=3276.40, cl=3331.27, vol=9218.7),
        BinanceData(symbol="ETH/USD", op=3331.27, hi=3352.10, lo=3295.55, cl=3308.62, vol=8047.3),
        BinanceData(symbol="ETH/USD", op=3308.62, hi=3320.44, lo=3252.90, cl=3264.18, vol=6873.5),
        BinanceData(symbol="ETH/USD", op=3264.18, hi=3312.75, lo=3258.30, cl=3299.06, vol=5740.9),
    ],
}


@initialize
def binance(req: BinanceRequest):
    """요청 자체를 원천 스테이지의 공유 컨텍스트로 사용한다."""

    return req


@binance
async def _(ctx: BinanceRequest, symbols: set[str]):
    """구독 심볼을 순환하며 요청한 주기의 USD 캔들을 0.5초 간격으로 발행한다.

    모의 데이터는 주기마다 10개뿐이므로 끝에 도달하면 처음부터 다시 반복한다.
    """

    while True:
        for i in range(10):
            for symbol in symbols:
                if symbol == "BTC/USD":
                    yield MOCK_BTC_USD[ctx.interval][i]
                elif symbol == "ETH/USD":
                    yield MOCK_ETH_USD[ctx.interval][i]
                else:
                    raise Exception(f"Unthinkable!!! - {symbol}")
                await sleep(0.5)


class UpbitRequest(GenerateModel):
    """KRW 마켓 캔들을 요청하는 원천 요청. 지원 주기가 USD 마켓과 다르다."""

    interval: Literal["5m", "30m", "1h"]


class OHLCData(DataModel):
    """정규화된 OHLC 출력 모델.

    KRW 원천은 이 모델을 그대로 발행하고(`symbol`은 `"BTC/KRW"` 표기),
    `OHLCRequest` binder는 심볼만 기초 자산으로 바꾸어 소비자에게 전달한다.
    USD 원천의 `BinanceData`도 이 모델로 변환된다.
    """

    open: float
    high: float
    low: float
    close: float
    volume: float


# 주기별로 10개의 캔들을 담은 KRW 마켓 모의 데이터. 필드 이름이 이미 정규화되어 있다.
MOCK_BTC_KRW: dict[str, list[OHLCData]] = {
    "5m": [
        OHLCData(
            symbol="BTC/KRW",
            open=93880000,
            high=94390000,
            low=93820000,
            close=94310000,
            volume=16.42,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94310000,
            high=94680000,
            low=94240000,
            close=94602000,
            volume=13.85,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94602000,
            high=94750000,
            low=94380000,
            close=94441000,
            volume=18.27,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94441000,
            high=94520000,
            low=93910000,
            close=94005000,
            volume=24.63,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94005000,
            high=94210000,
            low=93780000,
            close=94168000,
            volume=21.10,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94168000,
            high=94520000,
            low=94120000,
            close=94486000,
            volume=15.74,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94486000,
            high=94910000,
            low=94450000,
            close=94872000,
            volume=27.38,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94872000,
            high=95040000,
            low=94640000,
            close=94715000,
            volume=19.92,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94715000,
            high=94780000,
            low=94300000,
            close=94366000,
            volume=17.55,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94366000,
            high=94580000,
            low=94330000,
            close=94541000,
            volume=14.08,
        ),
    ],
    "30m": [
        OHLCData(
            symbol="BTC/KRW",
            open=93520000,
            high=94420000,
            low=93460000,
            close=94310000,
            volume=92.15,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94310000,
            high=94860000,
            low=94180000,
            close=94705000,
            volume=78.34,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94705000,
            high=95010000,
            low=94390000,
            close=94468000,
            volume=108.62,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94468000,
            high=94590000,
            low=93760000,
            close=93885000,
            volume=134.29,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=93885000,
            high=94340000,
            low=93610000,
            close=94276000,
            volume=117.53,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94276000,
            high=94880000,
            low=94210000,
            close=94812000,
            volume=96.08,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94812000,
            high=95460000,
            low=94750000,
            close=95384000,
            volume=142.77,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=95384000,
            high=95620000,
            low=95020000,
            close=95145000,
            volume=121.40,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=95145000,
            high=95280000,
            low=94480000,
            close=94596000,
            volume=104.91,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94596000,
            high=95120000,
            low=94540000,
            close=95038000,
            volume=88.26,
        ),
    ],
    "1h": [
        OHLCData(
            symbol="BTC/KRW",
            open=93210000,
            high=94180000,
            low=93050000,
            close=94022000,
            volume=182.46,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94022000,
            high=94960000,
            low=93940000,
            close=94805000,
            volume=165.31,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94805000,
            high=95220000,
            low=94470000,
            close=94612000,
            volume=214.77,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94612000,
            high=94740000,
            low=93520000,
            close=93760000,
            volume=268.05,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=93760000,
            high=94330000,
            low=93380000,
            close=94245000,
            volume=231.62,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94245000,
            high=95180000,
            low=94160000,
            close=95064000,
            volume=196.84,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=95064000,
            high=95810000,
            low=94980000,
            close=95692000,
            volume=279.13,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=95692000,
            high=95940000,
            low=95180000,
            close=95315000,
            volume=244.50,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=95315000,
            high=95480000,
            low=94620000,
            close=94738000,
            volume=208.36,
        ),
        OHLCData(
            symbol="BTC/KRW",
            open=94738000,
            high=95370000,
            low=94690000,
            close=95208000,
            volume=173.29,
        ),
    ],
}

MOCK_ETH_KRW: dict[str, list[OHLCData]] = {
    "5m": [
        OHLCData(
            symbol="ETH/KRW", open=4396000, high=4451000, low=4390000, close=4441000, volume=178.35
        ),
        OHLCData(
            symbol="ETH/KRW", open=4441000, high=4482000, low=4433000, close=4470000, volume=152.60
        ),
        OHLCData(
            symbol="ETH/KRW", open=4470000, high=4495000, low=4452000, close=4459000, volume=201.44
        ),
        OHLCData(
            symbol="ETH/KRW", open=4459000, high=4466000, low=4402000, close=4413000, volume=243.18
        ),
        OHLCData(
            symbol="ETH/KRW", open=4413000, high=4438000, low=4396000, close=4431000, volume=219.07
        ),
        OHLCData(
            symbol="ETH/KRW", open=4431000, high=4478000, low=4425000, close=4472000, volume=168.92
        ),
        OHLCData(
            symbol="ETH/KRW", open=4472000, high=4521000, low=4468000, close=4514000, volume=268.75
        ),
        OHLCData(
            symbol="ETH/KRW", open=4514000, high=4530000, low=4487000, close=4495000, volume=194.36
        ),
        OHLCData(
            symbol="ETH/KRW", open=4495000, high=4502000, low=4448000, close=4456000, volume=173.81
        ),
        OHLCData(
            symbol="ETH/KRW", open=4456000, high=4483000, low=4451000, close=4478000, volume=146.29
        ),
    ],
    "30m": [
        OHLCData(
            symbol="ETH/KRW", open=4368000, high=4462000, low=4355000, close=4448000, volume=1024.18
        ),
        OHLCData(
            symbol="ETH/KRW", open=4448000, high=4506000, low=4436000, close=4491000, volume=913.55
        ),
        OHLCData(
            symbol="ETH/KRW", open=4491000, high=4528000, low=4448000, close=4462000, volume=1187.02
        ),
        OHLCData(
            symbol="ETH/KRW", open=4462000, high=4478000, low=4384000, close=4397000, volume=1402.66
        ),
        OHLCData(
            symbol="ETH/KRW", open=4397000, high=4444000, low=4372000, close=4429000, volume=1256.31
        ),
        OHLCData(
            symbol="ETH/KRW", open=4429000, high=4512000, low=4418000, close=4498000, volume=1078.94
        ),
        OHLCData(
            symbol="ETH/KRW", open=4498000, high=4576000, low=4489000, close=4562000, volume=1493.27
        ),
        OHLCData(
            symbol="ETH/KRW", open=4562000, high=4590000, low=4520000, close=4534000, volume=1315.80
        ),
        OHLCData(
            symbol="ETH/KRW", open=4534000, high=4548000, low=4462000, close=4475000, volume=1142.09
        ),
        OHLCData(
            symbol="ETH/KRW", open=4475000, high=4530000, low=4468000, close=4519000, volume=987.43
        ),
    ],
    "1h": [
        OHLCData(
            symbol="ETH/KRW", open=4342000, high=4425000, low=4328000, close=4412000, volume=2043.55
        ),
        OHLCData(
            symbol="ETH/KRW", open=4412000, high=4498000, low=4405000, close=4487000, volume=1856.30
        ),
        OHLCData(
            symbol="ETH/KRW", open=4487000, high=4536000, low=4463000, close=4472000, volume=2317.84
        ),
        OHLCData(
            symbol="ETH/KRW", open=4472000, high=4490000, low=4370000, close=4389000, volume=2740.12
        ),
        OHLCData(
            symbol="ETH/KRW", open=4389000, high=4451000, low=4356000, close=4438000, volume=2405.67
        ),
        OHLCData(
            symbol="ETH/KRW", open=4438000, high=4540000, low=4429000, close=4526000, volume=2018.43
        ),
        OHLCData(
            symbol="ETH/KRW", open=4526000, high=4612000, low=4515000, close=4598000, volume=2893.20
        ),
        OHLCData(
            symbol="ETH/KRW", open=4598000, high=4630000, low=4548000, close=4561000, volume=2564.75
        ),
        OHLCData(
            symbol="ETH/KRW", open=4561000, high=4579000, low=4483000, close=4497000, volume=2179.06
        ),
        OHLCData(
            symbol="ETH/KRW", open=4497000, high=4568000, low=4490000, close=4552000, volume=1932.48
        ),
    ],
}


@initialize
def upbit(req: UpbitRequest):
    """요청 자체를 원천 스테이지의 공유 컨텍스트로 사용한다."""

    return req


@upbit
async def _(ctx: UpbitRequest, symbols: set[str]):
    """구독 심볼을 순환하며 요청한 주기의 KRW 캔들을 0.5초 간격으로 발행한다.

    모의 데이터는 주기마다 10개뿐이므로 끝에 도달하면 처음부터 다시 반복한다.
    """

    while True:
        for i in range(10):
            for symbol in symbols:
                if symbol == "BTC/KRW":
                    yield MOCK_BTC_KRW[ctx.interval][i]
                elif symbol == "ETH/KRW":
                    yield MOCK_ETH_KRW[ctx.interval][i]
                else:
                    raise Exception(f"Unthinkable!!! - {symbol}")
                await sleep(0.5)


class OHLCRequest(DependentModel):
    """견적 통화와 주기만 지정하면 거래소를 가리지 않는 파생 요청.

    `interval`은 두 원천이 함께 지원하는 주기로 제한한다.
    """

    quote: Literal["usd", "krw"]
    interval: Literal["5m", "1h"]


@OHLCRequest.require
def ohlc_requirement(req: OHLCRequest, symbols: set[str]):
    """견적 통화에 맞는 상위 요청과 그 거래소 표기의 심볼 집합을 함께 만든다.

    심볼 집합까지 받는 형태의 require 콜백이라 상위 원천에는 `"BTC"`가 아니라
    `"BTC/USD"` · `"BTC/KRW"`가 전달된다. 상위 요청이 무엇인지도 `quote` 값에 따라
    달라지므로 하나의 파생 요청이 두 원천 중 하나로 라우팅된다.
    """

    if req.quote == "usd":
        return BinanceRequest(interval=req.interval), {f"{s}/USD" for s in symbols}
    elif req.quote == "krw":
        return UpbitRequest(interval=req.interval), {f"{s}/KRW" for s in symbols}
    else:
        raise Exception(f"Unthinkable!!! - {req.quote}")


@initialize
def ohlc(req: OHLCRequest) -> OHLCRequest:
    """요청 자체를 파생 스테이지의 공유 컨텍스트로 사용한다."""

    return req


@ohlc
async def _(ctx: OHLCRequest, symbols: set[str], recv: Receiver):
    """상위 원천 데이터를 받아 `OHLCData`와 기초 자산 심볼로 정규화해 발행한다.

    `symbol`을 다시 기초 자산으로 되돌리는 것이 중요하다. `SharedSender`는 발행된
    데이터의 `symbol`로 구독자를 찾으므로, 거래소 표기 그대로 내보내면 어떤
    구독자에게도 전달되지 않는다.
    """

    while True:
        data = await recv()
        if ctx.quote == "usd":
            casted = cast_model(data, BinanceData)
            symbol = base_of(casted.symbol)
            if symbol not in symbols:
                print(f"warning: 요청한 심볼이 아니다. - {symbol}, {symbols}")
                continue
            yield OHLCData(
                symbol=symbol,
                open=casted.op,
                high=casted.hi,
                low=casted.lo,
                close=casted.cl,
                volume=casted.vol,
            )
        elif ctx.quote == "krw":
            casted_ohlc = cast_model(data, OHLCData)
            symbol = base_of(casted_ohlc.symbol)
            if symbol not in symbols:
                print(f"warning: 요청한 심볼이 아니다. - {symbol}")
                continue
            yield casted_ohlc.model_copy(update={"symbol": symbol})
