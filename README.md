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
- **Slow consumers are isolated** — one slow or stuck consumer doesn't hold back the shared stream
  or the other consumers; if it falls too far behind, only that consumer is cut off.
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
async def on_tick(data: DataModel) -> None: ...


async def on_error(failed: StageFailed) -> None:
    # failed.symbols: symbols this consumer lost, failed.cause: a summary of the cause
    ...


async with domain.subscribe(TickReq(exchange="mock"), on_tick, on_error) as sub:
    await sub.update({"BTC"})
    await sub.update({"ETH", "XRP"})  # replaces, does not add — BTC is dropped
    await sub.update(set())  # an empty set unsubscribes
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
    # once, when the last consumer leaves or the stage fails (close the connection, etc.)
    ...
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

Slow consumers are handled the same way. The core only puts data into a bounded queue per consumer,
so one slow or stuck consumer doesn't slow down the shared generator or the other consumers. When
the queue reaches `Domain(sender_buffer=1000)` items, the core doesn't drop data; it cuts the
consumer off and reports a `StageFailed` caused by `SenderOverflow`. The core can't know whether
your data is safe to drop.

| Where it falls behind | What is cut off |
| --- | --- |
| A consumer of a source or derived request | That consumer's whole subscription |
| A derived generator (can't keep up with its upstream) | That whole derived stage (every consumer is notified) |
| A session slot (slow pipeline or slow consumer) | That one symbol |
| The code reading `stream()` | It yields what it already received, then raises `StageFailed` and ends |

How long to wait on a stuck connection is up to the `Sender`. Wrap the send in `asyncio.timeout()`
and raise, and only that consumer drops off right away instead of waiting for the queue to fill. A
consumer that only needs the latest value can take data into its own queue and drop old items
itself, so it never gets cut off (ex25).

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

# if omitted, the first log call looks at TRADING_CORE_SETTINGS, then ./setting.toml
configure("setting.toml")
log = get_logger("my_app.strategy")
log.info("order signal", symbol="BTC", price=101.0)
```

Actually sending records to a log server is not implemented yet (`[log.server] enabled = true` is a
configuration error).

## Examples

`examples/` holds 34 **runnable** examples, one feature or event per file. Each file starts with
what it teaches and its expected output, and asserts at key points — so if an example runs to the
end, the behavior it shows still holds in the current code. The examples' comments and log output
are in Korean.

| Part | Examples | Covers |
| --- | --- | --- |
| 1 | ex01–06 | Source request basics: `stream`/`subscribe`, cleanup points, sharing, union, restarts |
| 2 | ex07–10 | Derived requests: `require`, symbol mapping, choosing an upstream, derived on derived |
| 3 | ex11–16 | Session requests: slots and `Pipeline`, unbind, no sharing, multi-step, multiple upstreams, `always` |
| 4 | ex17–24 | Failures: `StageFailed` cascades, consumer failure, cleanup failure, init failure, `SymbolRejected` |
| 5 | ex25–29 | Slow consumers: not holding others back, timeouts, source/derived/session/`stream()` falling behind |
| 6 | ex30–34 | Registration mistakes, identifiers, serialization, logging, multiple data types |

```bash
uv run examples/ex01_stream.py    # run one file directly
uv run examples/main.py ex01      # run by number
uv run examples/main.py serial    # run all, one after another, on one Domain
uv run examples/main.py parallel  # run all concurrently on one Domain
uv run examples/main.py --help    # list the examples
```

The full table of contents is in [examples/README.md](examples/README.md). If you're new, start at
ex01 and go in order. The ERROR logs and tracebacks in part 4 and in ex27–28 record failures the
examples cause on purpose.

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
- Isolating slow consumers with a bounded queue per consumer (cut off, never dropped, when they
  fall behind)
- JSON logging that records each record's origin

What binders or your application must handle:

- WebSocket/REST clients for specific exchanges or brokers
- Authentication, heartbeats, automatic reconnection, resubscription, rate limits (the core only
  reports failures and never retries)
- Mapping between exchange symbols and internal standard symbols
- Sequence gaps, snapshot/delta consistency, duplicates and reordering
- Order execution, portfolio, risk, storage, strategies and indicators
- Sharing streams across processes or servers
- How long to wait on a stuck connection (a timeout inside the `Sender`) and whether to drop old
  data (the core never drops, it only cuts off — ex25 shows taking data into your own queue and
  dropping it there)

## Development

```bash
uv run ruff check .
uv run ruff format --check .   # apply with: uv run ruff format .
uv run pyright
uv run pytest
```

After changing code, make all four checks pass. Tests don't run the examples, so if you changed
`src/`, also run `uv run examples/main.py serial`. The structure and design invariants are
described in [Architecture](#architecture) below.

## Architecture

The internal structure and design invariants. This section is for people changing the core or
digging into how it behaves; for usage, see "Core concepts" above and the examples.

### Layers

| File | Responsibility |
| --- | --- |
| `model.py` | `TrBaseModel` request/data models, the three identifiers, serialization and restoring, `Pipeline`/`Runnable` |
| `binder.py` | The `initialize()` decorator and the global `BindPack` registry (request type → callbacks) |
| `domain.py` | `Domain`, `Subscription`/`SharedStage`, lifecycle |
| `routing.py` | In-process delivery: `Channel`, `SymbolRouter`/`UpstreamRouters`, `PipelineSender` |
| `tasks.py` | Async `TaskManager` with cancellation by name |
| `ids.py` | Digest/id generation, finding the defining module |
| `logger.py` | Project-wide logging: a JSON logger whose console, file and log-server sinks are enabled by `[log]` in `setting.toml` |
| `exceptions.py` | Framework exceptions |

### Model hierarchy

```
TrBaseModel
├── BaseRequest            (_tr_model_type = "unregistered")
│   ├── SourceRequest      → "source" once bound
│   ├── DerivedRequest     → "derived" once bound (declares its upstream with require)
│   └── SessionRequest     → "session" once bound (stateful, never shared)
└── DataModel              (_tr_model_type = "data", symbol: str is the routing key)
```

`_tr_model_type` is recorded when `BindPack.set_*_cb()` runs, so **the module must be imported and
its decorators run** before a request can be used. `Domain` picks the stage kind from this value.
It is serialized into `tr_annotation.model_type`.

The three identifiers have different roles.

- **uid** (`_tr_uid`, `get_model_uid`): `Class@module:instanceID:seq`, for tracking individual
  models. The instance ID belongs to the process that created the model (`set_instance_id`/
  `get_instance_id`, `get_model_created_by`). By default it is the log origin `instance_id`
  (`service@host:pid`, `logger.get_identity()`) plus a 6-character random suffix, so it contains
  `@` and `:` — don't split a uid on separators. The first model created fixes the value, so if you
  `configure()` a different `service_name`, do it before creating models.
- **model_id** (`get_model_id`): `Class@module:field-structure-digest`. The binder registry key and
  what `cast_model()` matches on (exact match, not inheritance).
- **content_id** (`tr_content_id`): a digest of the model type plus its JSON serialization. **The basis
  for sharing.** It is cached; to compute it over selected fields use
  `compute_tr_content_id(include, exclude)`.

Models are **mutable**, and `__setattr__` invalidates the cached content_id. That is why they are not
hashable — don't use them in a `set` or as dict keys; key by content_id instead. Serialization adds
`tr_annotation`, and `load_model()` uses its `module_name`/`model_name` to find the class and restore
the model (`parse_dump()` only validates a dump). Because models are mutable, `Domain` **takes a copy**
of the request when subscribing (`_create_subscription()`). If the caller changes the request after
subscribing, the subscription stays bound to the original content, and `Subscription.request` also
returns a copy. Otherwise the stage would be looked up by the changed content_id and the original
stage would never close.

### Registration (binder.py)

```python
@initialize  # infers the request type from the init callback's first annotation
def naming(req: NamingAllReq) -> NamingAllContext:
    return NamingAllContext(req)  # context shared for the lifetime of the content_id


@naming  # SourceBinder.__call__ → the generate callback
async def _(ctx: NamingAllContext, symbols: set[str]):
    yield NamingAllData(...)


@naming.detached  # cleans up the context when the last subscription goes away
async def _(ctx: NamingAllContext): ...
```

- `initialize()` takes the **first value** of `get_type_hints(cb)` as the request type (the annotation
  is required). Depending on the request type it returns a `SourceBinder`, `DerivedBinder` or
  `SessionBinder`.
- A `DerivedRequest` declares its upstream with `require`, a decorator **without arguments**. It
  accepts two forms, told apart by the number of positional parameters, and normalizes both to
  `RequireCbWithSym` (read back with `resolve_upstream(symbols)`). Creating a derived stage without
  `require` raises `ModelError`.

  ```python
  @NamingReq.require  # RequireCb — takes only the request
  def _(req: NamingReq) -> origin.NamingAllReq:
      return origin.NamingAllReq()


  @PriceRequest.require  # RequireCbWithSym — also maps the symbols
  def _(req: PriceRequest, symbols: set[str]):
      return origin.TickReq(), {f"{s}/USD" for s in symbols}
  ```

- A derived binder takes `(ctx, symbols, recv: Receiver)`: it receives upstream data with `recv()`
  and narrows it with `cast_model()`.
- A `SessionRequest` gets `@x` (bind), `@x.unbind`, `@x.always` and `@x.detached`. Only one bind and
  one always can be registered; a second raises `BindError`. A derived request's `require` (declaring
  the upstream) and a session's `always` (a pipeline that is always attached) are different things.
- `BindPack._registry` is **process-global** (`BindPack.lookup(model_id)`). Registering the same
  `model_id` twice raises `BindError`.

### Execution (domain.py)

Core invariants:

1. **Sharing per content_id** — source and derived stages have exactly one `SharedStage` in
   `_shared_stages[content_id]`. Consumers of the same request share the context and the generator.
   Session requests are not shared.
2. **Symbol union** — `SymbolRouter` collects (Sender, symbols) pairs and passes only the **union** to
   the binder; output fans out only to the Senders subscribed to `data.symbol`.
3. **Restart only when the union changes** — if `current_symbols == active_symbols`, `update()` returns
   immediately. Otherwise it cancels the task by name (`pump()` closes the generator with `aclosing`)
   and creates a new generator (source and derived stages only).
4. **Two cleanup points** — the binder's `finally` runs per subscription update, `@x.detached` once per
   stage. When the union becomes empty, the stage is removed from the dict and the detach callback is
   called.
5. **`update(symbols)` replaces** (`SymbolRouter.replace()`). Passing an empty set removes that
   consumer's subscription.
6. **bind ↔ unbind pairing** — for every symbol a session opened with `bind_cb`, `unbind_cb` is called
   **exactly once**, whether the symbol leaves through `update()` or closes through `detach()`
   (shared `unbind_symbols()`). Closing slots (`close_slots()`) waits until the slot tasks release
   their names.
7. **Failures are not retried and are reported per symbol** — when an init callback, a source or
   derived generator, a pipeline, a bind callback or a consumer `Sender` raises, the stage or slot is
   taken down (or never brought up, for init), and each affected consumer gets a `StageFailed` holding
   **only its own symbols** through `on_error`. `update()` and `subscribe()` don't raise. When a source
   or derived stage fails (including init failures), the failure cascades to the derived stages and
   session slots that use it as their upstream (`__cause__` is the upstream's `StageFailed`). When a
   single `Sender` raises, only that Sender is detached and the shared generator keeps running. **A
   slow `Sender` doesn't hold others back either** — a shared subscription registers a `SenderOutbox`
   per consumer (a bounded queue plus a delivery task `{sub.id}:out`) with the router, and a session
   bounds its slot channels. When either fills up to `Domain(sender_buffer)` items, nothing is
   dropped; only that consumer (for a session, that slot) fails with `SenderOverflow`, because the
   core can't know whether data may be dropped. How long to wait on a stuck connection is up to the
   `Sender` itself (it raises once its timeout passes). A failed outbox raises that exception on the
   next call and goes through the router's `fail_sender()` path; when a send raises, it is also
   detached through `on_failed` without waiting for the next item. The channel through which a
   derived stage receives upstream data has the same bound. If the derived generator falls behind and
   it fills, the upstream is not held back; **the whole derived stage** fails with `SenderOverflow`.
   It doesn't raise into the upstream router, so it isn't reported as an upstream failure. `stream()`
   uses a one-item channel, so if the reader falls behind the outbox fills and the stream ends. Failed
   symbols leave the subscription; adding them back with `update()` brings up a new stage from init.
   Whether to hold on (reconnect and so on) is decided by the binder inside its generator. Sessions,
   like shared stages, run init on the first `update()`. Registration errors such as a missing binder
   (`DomainError`) still go to the caller. When a source or derived generator raises
   `SymbolRejected(symbols)`, the stage stays up; only those symbols are removed from the
   subscriptions and reported, and the stage restarts with the remaining symbols (`fail_symbols()`).
   A derived stage maps the upstream's failed symbols back to its own symbols
   (`fail_upstream_symbols()`, `resolve_upstream({s})` per downstream symbol) and removes only those.
   Rejecting only symbols that aren't subscribed is treated as a failure of the whole stage, so that
   it doesn't restart forever with the same union.
8. **A failing cleanup doesn't stop cleanup** — even if `detach_cb`, `unbind_cb` or a binder's
   `finally` raises, the rest of the cleanup runs to the end (`_run_cleanups()`, siblings are not
   cancelled) and only an ERROR log is written. Nothing is raised to the caller of `update()` or
   `detach()`.

Consumer API: `Domain.stream(req, symbols)` returns an async generator (wrapped in `aclosing`, so an
early `break` also cleans up). `Domain.subscribe(req, sender)` is the lower-level API where the caller
provides a `Sender` and replaces symbols with `sub.update(symbols)` (it returns a `Subscription`). The
`on_error` of `subscribe(req, sender, on_error)` receives `StageFailed` (`content_id`, `symbols`,
`cause`); without it only an ERROR log is written. `stream()` is a convenience API for tests and
examples, so it raises `StageFailed` and ends on failure. `get_shared_symbols(content_id)` returns the
symbol union of a shared stage (an empty set if it isn't shared). `Subscription` and `SharedStage` are
guarded by `_STAGE_CREATION_KEY` so they can only be created through `Domain`. The public API stays
small and doesn't hand out internal objects (stages).

Dependent streams: `_update_shared_stage()` creates or reuses the upstream `SharedStage` and connects
it to the downstream binder's `recv` through a bounded `Channel`. Instead of the channel, the upstream
router gets a `receive` function made once per stage (it puts without waiting and fails this stage
when full). Upstreams are shared by content_id and union too. Circular dependencies are not supported.
A derived stage watches a single upstream, so **a require callback cannot return different upstream
requests depending on the symbol.**

#### Sessions (SessionRequest)

Where a source or derived stage is "one symbol set → one generator", a session creates **one slot per
symbol**, and each slot attaches to an upstream source stage through a `Pipeline`
(`Domain._create_session_subscription()`; see ex11 and `SwingReq` in the tests). Sessions are stateful,
like chart analysis, so they aren't shared even when the content_id is the same (ex13).

```python
@swing  # bind — yields the Pipeline for one symbol
async def _(ctx: SwingCtx, symbol: str):
    yield TickReq()(f"{symbol}/USD") | SwingRunnable(symbol)


@swing.unbind  # when that symbol's slot closes
async def _(ctx: SwingCtx, symbol: str): ...


@swing.always  # a Pipeline attached regardless of the subscribed symbols
async def _(ctx: SwingCtx):
    yield TickReq()("HEARTBEAT/USD") | ...
```

**Keep upstream and downstream notation apart.** The `symbol` in `req(symbol)` is in upstream notation
(the `"BTC/USD"` the source stage knows, `Pipeline.upstream_symbol`); the `symbol` the bind callback
receives is in downstream notation (the `"BTC"` the consumer subscribed to). Tests using requests whose
two notations are identical won't catch a bug that swaps them.

- The symbols registered with the upstream subscription are `route.router.symbols` (upstream
  notation), not the downstream symbols.
- `_ALWAYS_SLOT` (`"__always__"`) is the sentinel key of the `always_cb` slot. It was never bound, so
  it is not an `unbind_cb` target, and it must not mix into real symbol calculations.
- `UpstreamRouters` keeps one `SymbolRouter` **object** per content_id (because of the `Sender`
  identity checks). `clear()` only empties the routers; after refilling, `prune()` removes entries
  without senders and detaches their upstream subscriptions within the same `update()`.
- Data flow: source stage → `SymbolRouter` (upstream notation) → `PipelineSender` → slot `Channel` →
  `_run_pipeline_slot()` runs `pipeline.invoke()` and passes the result to the consumer.
  `PipelineSender` puts into the slot channel without waiting (`try_send()`); when it is full it drops
  the item and fails that slot (waiting would stall the upstream).
- Slots close before the upstream subscription is updated, so `PipelineSender` swallows
  `ChannelClosed` for data arriving at a closed slot. Raising it would kill the shared upstream
  generator.
- When an upstream fails, the `StageFailed` that arrives in upstream notation is mapped back to the
  slot keys (downstream notation) that used that upstream and symbol (`on_upstream_failed()`). If the
  `always` slot fails, the whole session subscription fails and its context is cleaned up, so the next
  `update()` starts again from init.

#### Lock order in failure handling

Stage locks are only taken **downstream → upstream** (a downstream `update()` calls the upstream
`update()`). That is why failure notifications (`OnFail`) take no lock and only spawn a task with
`Domain._spawn()`; notifying downstream while holding an upstream lock would deadlock. The failure
handling task uses a generation number (`run_seq`) to tell whether an `update()` started a new
generator in the meantime, and an `update()` that reaches a removed stage (`retired`) is forwarded to
the stage registered now.

### TaskManager (tasks.py)

All of `Domain`'s generator loops run through `TaskManager.submit(coro, name)`. The name is the task's
identity and is **held even while the task is pending**. `cancel_by_name()` cancels and `gather`s a
running task, or records a pending one in `_cancelled_pending`; either way it **waits until the name is
released** (otherwise resubmitting the same name would collide). `live_count` is the number of
unfinished (pending + running) tasks. The submit, done and cancel hooks write DEBUG logs through
`logger.py`, and the exception hook writes an ERROR log (an exception that leaks up to a task is a bug
`Domain` failed to handle).

## License

[MIT License](LICENSE)
