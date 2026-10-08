# trading-core

**English** | [한국어](README.ko.md)

A **type-safe async streaming orchestration core** for real-time crypto and stock market streams.

`trading-core` is **not** a WebSocket client tied to a particular exchange or broker. It is a small,
general-purpose runtime for the work that keeps coming back whenever you handle real-time quotes,
trades, and order books: modeling requests, sharing subscriptions, routing by symbol, chaining
dependent streams, managing task and resource lifecycles, and reporting failures. You implement the
exchange-specific parts — authentication, subscribe messages, response parsing — as **binders**
(callbacks attached to a request type), and the core runs everything else the same way.

## What it solves

Many strategies and indicators subscribe to the same instruments at once. If every consumer opens
its own connection, connections and traffic multiply, and each consumer has to handle
subscribing, unsubscribing, and shutdown on its own.

```text
Consumer A (BTC, ETH) ─┐
                       ├─→ shared source stage (BTC, ETH, XRP) ─→ fan-out by symbol ─→ each consumer
Consumer B (ETH, XRP) ─┘
```

- **Requests with equal content are shared** — requests whose field values match share one context
  and one generator.
- **Symbol union** — a binder receives only the union of the symbols its consumers want, and
  restarts only when that union changes.
- **Fan-out by symbol** — data goes only to the consumers subscribed to its symbol.
- **Dependent streams** — feed one request's output into another request; upstream stages are
  shared too.
- **Per-symbol state** — computations that keep state per symbol, such as chart analysis, get a
  separate slot per symbol.
- **Explicit lifecycle** — separate cleanup points for when the subscription set changes and when
  the last consumer leaves.
- **Failure notification** — failures are not hidden behind retries; each affected consumer is told
  exactly which of its symbols it lost.
- **Typed boundaries** — requests and data are Pydantic models, with validation, serialization, and
  restoring as-is.

## Installation

- Python 3.14 or later
- One runtime dependency: [Pydantic 2](https://docs.pydantic.dev/)
- Recommended package manager: [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/bynaki/trading-core.git
cd trading-core
uv sync
```

To depend on it from another uv project, use a local path or the Git repository.

```bash
uv add /path/to/trading-core
uv add "git+https://github.com/bynaki/trading-core.git"
```

## Quick start

Using the core splits into two sides. The **binder side** defines request models and registers how
to produce data when such a request arrives (in real code, this is where you connect to the
exchange and parse messages). The **consumer side** hands a request and symbols to a `Domain` and
receives data.

```python
import asyncio

from trading_core import DataModel, Domain, SourceRequest, cast_model, initialize


# ----- binder side -----
class TickReq(SourceRequest):
    exchange: str  # field values are the request's "content"; equal content is shared


class TickData(DataModel):  # DataModel already has a `symbol` field (the routing key)
    price: float


@initialize  # the first parameter's annotation (TickReq) decides which request this binds
def tick(req: TickReq) -> TickReq:
    """init callback: called once when the stage starts; builds the context (a connection, etc.)."""
    return req


@tick
async def _(ctx: TickReq, symbols: set[str]):
    """generate callback: receives the union of subscribed symbols and yields data forever."""
    price = 100.0
    while True:
        for symbol in sorted(symbols):
            yield TickData(symbol=symbol, price=price)
        price += 1
        await asyncio.sleep(0.2)


# ----- consumer side -----
async def main() -> None:
    domain = Domain()
    await domain.start()
    try:
        async with domain.stream(TickReq(exchange="mock"), {"BTC", "ETH"}) as stream:
            async for data in stream:
                tick_data = cast_model(data, TickData)  # DataModel → TickData
                print(tick_data.symbol, tick_data.price)
                if tick_data.price >= 102:
                    break  # leaving the block unsubscribes and closes the generator
    finally:
        await domain.stop()


asyncio.run(main())
```

A request can be used only after its `@initialize` has run, so the module that defines the binders
must be imported before the `Domain` uses them.

## Core concepts

### Three kinds of requests

| Request | What it does | Shared | Binder receives |
| --- | --- | --- | --- |
| `SourceRequest` | Pulls data from outside | Yes, by content | `(ctx, symbols)` |
| `DerivedRequest` | Transforms another request's data | Yes, by content | `(ctx, symbols, recv)` |
| `SessionRequest` | Runs a per-symbol pipeline with its own state | No | `(ctx, symbol)` per symbol |

All data is a `DataModel` and is routed to consumers by its `symbol` field.

### Subscribing: `stream()` and `subscribe()`

`stream(req, symbols)` is a convenience API that fixes the symbols up front and runs to the end. To
change symbols while the subscription stays open, use `subscribe()`. Data arrives through a
`Sender` (an async function that takes one data item).

```python
async def on_tick(data: DataModel) -> None:
    ...

async def on_error(failed: StageFailed) -> None:
    ...  # failed.symbols: symbols this consumer lost, failed.cause: a summary of the cause

async with domain.subscribe(TickReq(exchange="mock"), on_tick, on_error) as sub:
    await sub.update({"BTC"})
    await sub.update({"ETH", "XRP"})  # replaces, does not add — BTC is dropped
    await sub.update(set())           # an empty set unsubscribes
```

`domain.get_shared_symbols(req.tr_content_id)` shows the symbol union a shared stage is currently
running.

### Two cleanup points

```python
@tick
async def _(ctx: Connection, symbols: set[str]):
    try:
        ...  # yield
    finally:
        ...  # each time the generator restarts because the subscribed symbols changed

@tick.detached
async def _(ctx: Connection):
    ...  # once, when the last consumer leaves or the stage fails (close the connection, etc.)
```

The context survives restarts. If a cleanup callback raises, the rest of the cleanup still runs to
completion.

### Derived requests: building on other streams

Declare the upstream request with `require`, and the `Domain` starts the upstream stage and wires
it in. Consumers don't need to know about the upstream request. If the upstream names symbols
differently, `require` can map the symbols as well.

```python
class PriceReq(DerivedRequest):
    currency: str


@PriceReq.require
def _(req: PriceReq, symbols: set[str]):  # drop the symbols parameter to pass symbols unchanged
    return TickReq(exchange="mock"), {f"{s}/USD" for s in symbols}


@initialize
def price(req: PriceReq) -> PriceReq:
    return req


@price
async def _(ctx: PriceReq, symbols: set[str], recv: Receiver):
    while True:
        tick_data = cast_model(await recv(), TickData)  # receive upstream data one item at a time
        yield PriceData(symbol=tick_data.symbol.removesuffix("/USD"), price=tick_data.price)
```

Several derived requests with different content still share one upstream stage when their upstream
request is the same, and the upstream receives the union of the symbols they register. Derived
requests can be stacked on other derived requests. Circular dependencies are not supported, and
`require` cannot pick a different upstream request per symbol.

### Session requests: per-symbol pipelines with state

A session request creates one **slot** per symbol, and each slot attaches to an upstream source
stage through the `Pipeline` its bind callback yields. Steps (`Runnable`) are created per slot, so
they can safely hold per-symbol state.

```python
class Change(Runnable[TickData, ChangeData]):
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.last: float | None = None  # state for this symbol only

    async def invoke(self, input: TickData) -> ChangeData | None:
        last, self.last = self.last, input.price
        if last is None:
            return None  # returning None stops this item here
        return ChangeData(symbol=self.symbol, change=input.price - last)


@initialize
def change(req: ChangeReq) -> ChangeReq:
    return req


@change  # bind: called once for each newly subscribed symbol
async def _(ctx: ChangeReq, symbol: str):
    yield TickReq(exchange="mock")(f"{symbol}/USD") | Change(symbol)


@change.unbind  # when that symbol's slot closes; exactly once per bind
async def _(ctx: ChangeReq, symbol: str): ...
```

`@change.always` attaches a pipeline that runs regardless of the subscribed symbols, and a bind
callback that yields several pipelines attaches one slot to several upstreams. The `symbol` a bind
callback receives is the **downstream notation** the consumer used (`BTC`); the head of the
pipeline takes the **upstream notation** the upstream knows (`BTC/USD`).

### Failure handling

The core **does not retry.** When an init callback, generator, bind callback, or pipeline step
raises, the core takes down that stage or slot and notifies each affected consumer through
`on_error` with a `StageFailed` holding **only that consumer's symbols**. The failure cascades to
derived and session stages built on top of it, and their `__cause__` points to the upstream
`StageFailed`.

- Failed symbols are removed from the subscription. To receive them again, the consumer adds them
  back with `update()`, and a new stage starts from init.
- If one consumer (`Sender`) raises, only that consumer is detached; the shared generator keeps
  running.
- When a binder can't serve a single symbol (a delisting, for example), it raises
  `SymbolRejected`. The stage keeps running with the remaining symbols and reports only that
  symbol as failed.
- `update()` and `subscribe()` don't raise failures. Without `on_error`, only an ERROR log is
  written. `stream()` raises `StageFailed` and ends.
- Registration mistakes such as a missing binder go straight to the caller as `BindError`,
  `DomainError`, or `ModelError`.

Whether to ride out harmless disconnects (by reconnecting, say) is up to the binder, inside its
generator. If the core retried too, retries would multiply at every stage of a multi-stage request.

### Model identifiers and serialization

| Identifier | Identifies | Used for |
| --- | --- | --- |
| content_id (`req.tr_content_id`) | Model type + content | Key for sharing stages |
| model_id (`get_model_id`) | Class and field structure | Binder registry key, `cast_model()` matching |
| uid (`get_model_uid`) | A single instance | Tracing which process created which model |

Models are mutable, and changing one recomputes its content_id. They are therefore not hashable;
use the content_id as the key in sets and dicts. `Domain` takes a copy of the request when you
subscribe, so editing the original afterwards does not affect the subscription.

`model_dump()` attaches a `tr_annotation`, which `load_model()` uses to find the original class and
restore the model. `parse_dump()` only validates a dump; mismatched input raises
`ModelValidationError`.

### Logging

`trading_core.logger` is a JSON logger with console, file, and log-server sinks that can be turned
on and off. Settings live in the `[log]` section of `setting.toml` (every key is described in
[setting.example.toml](setting.example.toml)), and each record carries its origin as `service`,
`host`, and `pid`. Loggers from the core and from your application are collected into the same
sinks.

```python
from trading_core.logger import configure, get_logger

configure("setting.toml")  # if omitted, the first log call looks at TRADING_CORE_SETTINGS, then ./setting.toml
log = get_logger("my_app.strategy")
log.info("order signal", symbol="BTC", price=101.0)
```

Actually sending records to a log server is not implemented yet (`[log.server] enabled = true` is a
configuration error).

## Examples

`examples/` holds 30 **runnable** examples, one feature or event per file. Each file starts with
what it teaches and its expected output, and asserts at key points — so if an example runs to the
end, the behavior it shows still holds in the current code. The examples' comments and log output
are in Korean.

| Part | Examples | Covers |
| --- | --- | --- |
| 1 | ex01–06 | Source request basics: `stream`/`subscribe`, cleanup points, sharing, union, restarts |
| 2 | ex07–10 | Derived requests: `require`, symbol mapping, choosing an upstream, derived on derived |
| 3 | ex11–16 | Session requests: slots and `Pipeline`, unbind, no sharing, multi-step, multiple upstreams, `always` |
| 4 | ex17–24 | Failures: `StageFailed` cascades, consumer failure, cleanup failure, init failure, `SymbolRejected` |
| 5 | ex25–30 | Slow consumers, registration mistakes, identifiers, serialization, logging, multiple data types |

```bash
uv run examples/ex01_stream.py    # run one file directly
uv run examples/main.py ex01      # run by number
uv run examples/main.py serial    # run all, one after another, on one Domain
uv run examples/main.py parallel  # run all concurrently on one Domain
uv run examples/main.py --help    # list the examples
```

The full table of contents is in [examples/README.md](examples/README.md). If you're new, start at
ex01 and go in order. The ERROR logs and tracebacks in part 4 record failures the examples cause on
purpose.

## Scope and limitations

Version `0.1.0`.

What the core handles:

- Request and data models, content-based identifiers, serialization and restoring
- Binder registration and lookup by request type
- In-memory sharing of stages for requests with equal content, symbol union management, and
  per-consumer routing
- Dependent stream chaining and session streams with per-symbol state
- Async task cancellation and cleanup points for binders and contexts
- Per-symbol failure notification
- JSON logging that records each record's origin

What binders or your application must handle:

- WebSocket/REST clients for specific exchanges or brokers
- Authentication, heartbeats, automatic reconnection, resubscription, rate limits (the core only
  reports failures and never retries)
- Mapping between exchange symbols and internal standard symbols
- Sequence gaps, snapshot/delta consistency, duplicates and reordering
- Order execution, portfolio, risk, storage, strategies and indicators
- Sharing streams across processes or servers
- Bounded queues and backpressure (a slow consumer slows the shared stream down — ex25 shows how to
  decouple it with its own queue)

## Development

```bash
uv run ruff check .
uv run ruff format --check .   # apply with: uv run ruff format .
uv run pyright
uv run pytest
```

After changing code, make all four checks pass. Tests don't run the examples, so if you changed
`src/`, also run `uv run examples/main.py serial`. The structure and design invariants are
documented in [AGENTS.md](AGENTS.md) (in Korean).

## License

[MIT License](LICENSE)
