import re

_SYMBOL_PATTERN = re.compile(r"^([A-Z0-9]+)/([A-Z0-9]+)$")


def base_of(symbol: str) -> str:
    """`"BTC/USD"`처럼 `기초/견적` 형식인 심볼에서 기초 자산(`"BTC"`)만 뽑아낸다."""
    matched = _SYMBOL_PATTERN.match(symbol)
    if matched is None:
        raise ValueError(f"'{symbol}'은(는) '기초/견적' 형식의 심볼이 아니다")
    return matched.group(1)


def quote_of(symbol: str) -> str:
    """`"BTC/USD"`처럼 `기초/견적` 형식인 심볼에서 견적 자산(`"USDT"`)만 뽑아낸다."""
    matched = _SYMBOL_PATTERN.match(symbol)
    if matched is None:
        raise ValueError(f"'{symbol}'은(는) '기초/견적' 형식의 심볼이 아니다")
    return matched.group(2)


print(base_of("BTC/USD"))
print(quote_of("BTC/USD"))
