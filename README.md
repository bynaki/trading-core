# trading-core

A general-purpose framework for building trading systems. `trading-core`
provides the orchestration primitives — typed data models, dispatchable tasks,
composable pipelines, and request domains — so you can assemble strategies,
indicators, and data flows on top of it. Market-agnostic, built on
[pydantic](https://docs.pydantic.dev/).

## Setup

```bash
uv sync
```

## Concepts

`trading-core` is built around a small set of typed primitives:

- **`DataModel`** — a typed message that flows through the system. Every
  instance carries its own provenance (`tr_annotation`): a structure-based
  `model_id` (used as the dispatch key) and a content-based id (used for
  deduplication/caching).
- **`RequestModel`** — an entry point. Calling it with a symbol builds a
  `Sequence` bound to that symbol.
- **`Sequence`** — a pipeline of `Runnable` steps, composed with the `|`
  operator. The originating request and symbol are preserved across the chain.
- **`task`** — a unit of work with its own context. Handlers are registered per
  input type and dispatched by the input's `model_id`.
- **`domain`** — registers a handler for a given `RequestModel` type in a
  global registry (duplicate request types are rejected).

A `Runnable` is anything with `async def invoke(self, input: DataModel) ->
DataModel | None`.

## Usage

Define typed data models and a task that dispatches on them:

```python
from trading_core import DataModel, task


class Ping(DataModel):
    msg: str = ""


class Pong(DataModel):
    msg: str = ""


class Counter:
    def __init__(self) -> None:
        self.count = 0


@task(Counter)
def upper() -> Counter:
    return Counter()


@upper.on(Ping)
async def _on_ping(ctx: Counter, input: Ping) -> Pong:
    ctx.count += 1
    return Pong(msg=input.msg.upper())


result = await upper().invoke(Ping(msg="hi"))
# -> Pong(msg="HI")
```

Build a symbol-bound pipeline from a request and compose steps with `|`:

```python
from trading_core import RequestModel


class QuoteReq(RequestModel):
    pass


seq = QuoteReq()("BTC") | upper()
seq.symbol       # -> "BTC"
seq.req_model    # -> QuoteReq(...)
```

Register a domain for a request type:

```python
from trading_core import DomainContext, domain


@domain(QuoteReq)
def quotes(req: QuoteReq) -> DomainContext[QuoteReq]:
    return DomainContext(req)
```

## Use from another project

`trading-core` is a self-contained package, so other projects can depend on it
directly without publishing:

```bash
# local path
uv add /path/to/trading-core

# git repository
uv add "https://github.com/bynaki/trading-core.git"
```

## Development

```bash
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy                # type check
uv run pytest              # tests
```

## Layout

```
src/trading_core/
├── model.py      # typed models: DataModel, RequestModel, Sequence, Runnable
├── definer.py    # orchestration: task, domain, DomainContext
└── helper.py     # id / digest helpers
```

## License

Released under the [MIT License](LICENSE).
