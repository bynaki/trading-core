"""`logger.py` 명세 — 설정 탐색·검증, 레코드 형식, 발신처 식별, 싱크, 수명 주기."""

import asyncio
import inspect
import io
import json
import logging
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from trading_core import logger as trlog
from trading_core.exceptions import LogConfigError
from trading_core.logger import (
    ConsoleSink,
    FileSink,
    LogSettings,
    ServerSettings,
    ServerSink,
    configure,
    get_logger,
    load_settings,
    shutdown,
)


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """CWD와 환경변수를 격리하고, 끝나면 루트 로거를 원래대로 돌려 둔다."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(trlog.SETTINGS_ENV, raising=False)
    yield
    shutdown()
    trlog._state.closed = False  # 다음 테스트에서 자동 구성을 다시 시험할 수 있게


def write_settings(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def file_config(tmp_path: Path, *, log: str = "", tail: str = "") -> Path:
    """콘솔을 끄고 JSON 파일 싱크만 켠 설정. `log`는 `[log]` 키, `tail`은 뒤에 붙일 테이블."""

    out = (tmp_path / "out.jsonl").as_posix()
    body = f"""
[log]
level = "DEBUG"
{log}

[log.console]
enabled = false

[log.file]
enabled = true
level = "DEBUG"
path = "{out}"

{tail}
"""
    return write_settings(tmp_path / "setting.toml", body)


def read_records(tmp_path: Path) -> list[dict[str, Any]]:
    """`shutdown()`으로 큐를 비운 뒤 파일 싱크의 레코드를 읽는다."""

    shutdown()
    lines = (tmp_path / "out.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


# ---------------------------------------------------------------------------
# 설정 탐색과 검증
# ---------------------------------------------------------------------------


def test_defaults_without_a_settings_file():
    settings = load_settings()

    assert settings == LogSettings()
    assert settings.console.enabled and settings.console.format == "text"
    assert not settings.file.enabled and not settings.server.enabled


def test_search_order_is_argument_then_env_then_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def settings_named(name: str) -> Path:
        return write_settings(tmp_path / f"{name}.toml", f'[log]\nservice_name = "{name}"\n')

    write_settings(tmp_path / "setting.toml", '[log]\nservice_name = "cwd"\n')
    assert load_settings().service_name == "cwd"

    monkeypatch.setenv(trlog.SETTINGS_ENV, str(settings_named("env")))
    assert load_settings().service_name == "env"

    assert load_settings(settings_named("arg")).service_name == "arg"


def test_other_categories_are_ignored(tmp_path: Path):
    write_settings(tmp_path / "setting.toml", '[exchange]\nkey = 1\n\n[log]\nlevel = "ERROR"\n')

    assert load_settings().level == "ERROR"


def test_a_named_but_missing_file_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(LogConfigError):
        configure(tmp_path / "nope.toml")

    monkeypatch.setenv(trlog.SETTINGS_ENV, str(tmp_path / "nope.toml"))
    with pytest.raises(LogConfigError):
        configure()


@pytest.mark.parametrize(
    "body",
    [
        "[log]\nunknown = 1\n",
        '[log.console]\nformat = "yaml"\n',
        '[log.console]\nstream = "stdlog"\n',
        '[log]\nlevel = "LOUD"\n',
        '[log.levels]\nasyncio = "LOUD"\n',
        "[log\n",
        'log = "not a table"\n',
    ],
)
def test_invalid_settings_are_rejected(tmp_path: Path, body: str):
    with pytest.raises(LogConfigError):
        configure(write_settings(tmp_path / "bad.toml", body))


# ---------------------------------------------------------------------------
# 레코드
# ---------------------------------------------------------------------------


def test_record_carries_its_origin(tmp_path: Path):
    configure(file_config(tmp_path, log='service_name = "trader-kr-01"'))

    get_logger("myapp").info("hello")

    [rec] = read_records(tmp_path)
    host = socket.gethostname()
    assert rec["service"] == "trader-kr-01"
    assert rec["host"] == host
    assert rec["pid"] == os.getpid()
    assert rec["instance_id"] == f"trader-kr-01@{host}:{os.getpid()}"


def test_get_identity_matches_the_records_origin(tmp_path: Path):
    """`get_identity()`는 구성 전엔 설정만 읽어 계산하고(구성은 안 한다) 구성 뒤엔 그 값이다."""

    path = file_config(tmp_path, log='service_name = "trader-kr-01"')
    before = trlog.get_identity()
    assert before.instance_id == f"trader-kr-01@{socket.gethostname()}:{os.getpid()}"
    assert not trlog._state.configured

    configure(path)
    assert trlog.get_identity() is trlog._state.identity
    get_logger("myapp").info("hello")
    [rec] = read_records(tmp_path)
    assert rec["instance_id"] == before.instance_id


def test_service_name_defaults_to_the_hostname(tmp_path: Path):
    configure(file_config(tmp_path))

    get_logger("myapp").info("hello")

    [rec] = read_records(tmp_path)
    assert rec["service"] == socket.gethostname()


def test_logger_names_from_any_package_reach_the_same_sinks(tmp_path: Path):
    configure(file_config(tmp_path))

    get_logger("trading_core.domain").info("inside")
    get_logger("myapp.strategy").info("outside")

    recs = read_records(tmp_path)
    assert [(r["logger"], r["msg"]) for r in recs] == [
        ("trading_core.domain", "inside"),
        ("myapp.strategy", "outside"),
    ]


def test_record_location_is_the_caller(tmp_path: Path):
    configure(file_config(tmp_path))
    log = get_logger("myapp")

    frame = inspect.currentframe()
    assert frame is not None
    line = frame.f_lineno + 1
    log.warning("here")

    [rec] = read_records(tmp_path)
    assert (rec["module"], rec["func"], rec["line"]) == (
        "test_logger",
        "test_record_location_is_the_caller",
        line,
    )


def test_fields_are_made_json_safe(tmp_path: Path):
    class Point(BaseModel):
        x: int

    class Opaque:
        def __repr__(self) -> str:
            return "<opaque>"

    configure(file_config(tmp_path))

    get_logger("myapp").info(
        "fields", msg="field named msg", point=Point(x=1), tags={"a"}, obj=Opaque(), n=None
    )

    [rec] = read_records(tmp_path)
    assert rec["msg"] == "fields"
    assert rec["fields"] == {
        "msg": "field named msg",
        "point": {"x": 1},
        "tags": ["a"],
        "obj": "<opaque>",
        "n": None,
    }


def test_exception_is_serialized_apart_from_the_message(tmp_path: Path):
    configure(file_config(tmp_path))
    log = get_logger("myapp")

    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("failed", step=1)
    log.info("no exception")

    failed, plain = read_records(tmp_path)
    assert failed["msg"] == "failed"
    assert failed["level"] == "ERROR"
    assert failed["fields"] == {"step": 1}
    assert failed["exc"]["type"] == "ValueError"
    assert failed["exc"]["message"] == "boom"
    assert "ValueError: boom" in failed["exc"]["traceback"]
    assert plain["exc"] is None


async def test_asyncio_task_name_is_captured(tmp_path: Path):
    configure(file_config(tmp_path))
    log = get_logger("myapp")

    async def probe():
        log.info("in task")

    await asyncio.create_task(probe(), name="probe-task")

    [rec] = read_records(tmp_path)
    assert rec["task"] == "probe-task"


def test_task_is_null_outside_an_event_loop(tmp_path: Path):
    configure(file_config(tmp_path))

    get_logger("myapp").info("no loop")

    [rec] = read_records(tmp_path)
    assert rec["task"] is None


# ---------------------------------------------------------------------------
# 싱크와 레벨
# ---------------------------------------------------------------------------


def test_console_text_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    body = '[log]\nservice_name = "svc"\n\n[log.console]\nlevel = "INFO"\n'
    configure(write_settings(tmp_path / "setting.toml", body))

    get_logger("myapp.console").info("안녕", a=1, b="x")
    shutdown()

    err = capsys.readouterr().err
    prefix = f"[svc@{socket.gethostname()}:{os.getpid()}] myapp.console: 안녕 {{a=1, b=x}}"
    assert prefix in err
    assert " INFO  " in err


def test_console_simple_text_format_drops_time_and_origin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    body = '[log]\nservice_name = "svc"\n\n[log.console]\nformat = "text.simple"\n'
    configure(write_settings(tmp_path / "setting.toml", body))

    log = get_logger("myapp.console")
    log.info("안녕", a=1, b="x")
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("실패")
    shutdown()

    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == "INFO  myapp.console: 안녕 {a=1, b=x}"
    assert lines[1] == "ERROR myapp.console: 실패"
    assert lines[-1] == "ValueError: boom"  # 트레이스백은 text와 같이 붙는다
    assert not any("svc@" in line for line in lines)


def test_text_fields_stay_inline_while_short_and_flat(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    configure(write_settings(tmp_path / "setting.toml", '[log.console]\nformat = "text.simple"\n'))

    get_logger("t").info("짧음", a=1, xs=[1, 2], meta={})  # 빈 dict는 펼치지 않는다
    shutdown()

    assert capsys.readouterr().err.splitlines() == ["INFO  t: 짧음 {a=1, xs=[1, 2], meta={}}"]


def test_text_fields_expand_dicts_under_their_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    configure(write_settings(tmp_path / "setting.toml", '[log.console]\nformat = "text.simple"\n'))

    class Order(BaseModel):
        symbol: str
        qty: float

    get_logger("t").info("주문", id=7, order=Order(symbol="BTC", qty=1.5))
    shutdown()

    assert capsys.readouterr().err.splitlines() == [
        "INFO  t: 주문 {id=7}",
        "  order = {",
        '    "symbol": "BTC",',
        '    "qty": 1.5',
        "  }",
    ]


def test_text_fields_bundle_into_one_block_when_too_long(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    configure(write_settings(tmp_path / "setting.toml", '[log.console]\nformat = "text"\n'))

    symbols = [f"SYMBOL_{c}" for c in "ABCDEFGHIJ"]
    get_logger("t").info("긺", run=3, symbols=symbols, order={"qty": 1})
    shutdown()

    head, *rest = capsys.readouterr().err.splitlines()
    assert head.endswith("] t: 긺")  # text 형식도 같은 규칙이다
    split = rest.index("  order = {")
    bundled = "\n".join(line.removeprefix("  ") for line in rest[:split])
    assert json.loads(bundled) == {"run": 3, "symbols": symbols}
    assert rest[split:] == ["  order = {", '    "qty": 1', "  }"]


def test_console_json_format_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    body = '[log.console]\nformat = "json"\nstream = "stdout"\n'
    configure(write_settings(tmp_path / "setting.toml", body))

    get_logger("myapp").warning("json", k=1)
    shutdown()

    out = capsys.readouterr().out
    rec = json.loads(out.strip())
    assert (rec["msg"], rec["fields"]) == ("json", {"k": 1})


def test_sink_levels_are_independent(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    out = (tmp_path / "out.jsonl").as_posix()
    body = f"""
[log]
level = "DEBUG"

[log.console]
level = "WARNING"

[log.file]
enabled = true
level = "DEBUG"
path = "{out}"
"""
    configure(write_settings(tmp_path / "setting.toml", body))
    log = get_logger("myapp")

    log.debug("quiet")
    log.warning("loud")

    recs = read_records(tmp_path)
    err = capsys.readouterr().err
    assert [r["msg"] for r in recs] == ["quiet", "loud"]
    assert "loud" in err and "quiet" not in err


def test_root_level_filters_before_the_sinks(tmp_path: Path):
    out = (tmp_path / "out.jsonl").as_posix()
    body = '[log]\nlevel = "WARNING"\n\n[log.console]\nenabled = false\n\n'
    body += f'[log.file]\nenabled = true\nlevel = "DEBUG"\npath = "{out}"\n'
    configure(write_settings(tmp_path / "setting.toml", body))

    get_logger("myapp").info("dropped")
    get_logger("myapp").warning("kept")

    assert [r["msg"] for r in read_records(tmp_path)] == ["kept"]


def test_level_overrides_apply_by_name_and_are_reset(tmp_path: Path):
    configure(file_config(tmp_path, tail='[log.levels]\n"noisy" = "ERROR"\n'))

    get_logger("noisy.child").warning("silenced")
    get_logger("myapp").warning("kept")
    get_logger("noisy").error("loud enough")

    assert [r["msg"] for r in read_records(tmp_path)] == ["kept", "loud enough"]
    assert logging.getLogger("noisy").level == logging.NOTSET


def test_shutdown_restores_the_root_logger(tmp_path: Path):
    root = logging.getLogger()
    before = (root.level, list(root.handlers))

    configure(file_config(tmp_path))
    assert root.level == logging.DEBUG
    shutdown()

    assert (root.level, list(root.handlers)) == before


def test_file_sink_rotates(tmp_path: Path):
    configure(file_config(tmp_path))
    [sink] = trlog._state.sinks
    assert isinstance(sink, FileSink)
    log = get_logger("myapp")

    log.info("before")
    out = tmp_path / "out.jsonl"
    deadline = time.monotonic() + 2
    while not out.read_text(encoding="utf-8") and time.monotonic() < deadline:
        time.sleep(0.001)  # 리스너 스레드가 "before"를 쓸 때까지
    sink.rolloverAt = 0  # 다음 레코드에서 회전하게 한다(시간을 기다리지 않는다)
    log.info("after")
    shutdown()

    rotated = [p for p in tmp_path.iterdir() if p.name.startswith("out.jsonl.")]
    assert len(rotated) == 1
    assert json.loads(rotated[0].read_text(encoding="utf-8"))["msg"] == "before"
    assert json.loads((tmp_path / "out.jsonl").read_text(encoding="utf-8"))["msg"] == "after"


def test_failing_sink_warns_once_and_drops_the_record(capsys: pytest.CaptureFixture[str]):
    class Broken(io.StringIO):
        def write(self, s: str) -> int:
            raise OSError("disk gone")

    sink = ConsoleSink(Broken())
    record = logging.LogRecord("myapp", logging.INFO, __file__, 1, "x", None, None)

    sink.handle(record)
    sink.handle(record)

    err = capsys.readouterr().err
    assert err.count("ConsoleSink 출력 실패") == 1
    assert "disk gone" in err


# ---------------------------------------------------------------------------
# 로그서버 싱크 (뼈대)
# ---------------------------------------------------------------------------


def test_enabling_the_server_sink_fails_fast_and_keeps_the_current_config(tmp_path: Path):
    configure(file_config(tmp_path))
    server = write_settings(tmp_path / "server.toml", "[log.server]\nenabled = true\n")

    with pytest.raises(LogConfigError, match="아직 구현되지 않았다"):
        configure(server)
    get_logger("myapp").info("still here")

    assert [r["msg"] for r in read_records(tmp_path)] == ["still here"]


def test_server_sink_batches_and_keeps_what_it_could_not_send():
    sent: list[list[str]] = []
    failing = True

    class Probe(ServerSink):
        def send_batch(self, lines: list[str]) -> None:
            if failing:
                raise ConnectionError
            sent.append(lines)

    sink = Probe(ServerSettings(level="DEBUG", batch_size=2, max_buffer=3))

    def emit(msg: str):
        sink.handle(logging.LogRecord("myapp", logging.INFO, __file__, 1, msg, None, None))

    for msg in "abcd":
        emit(msg)  # 보내지 못해 쌓이다가, 넷째에서 가장 오래된 a를 버린다
    assert sink.dropped == 1

    failing = False
    sink.close()  # 남은 것을 batch_size씩 보낸다
    assert sent == [["b", "c"], ["d"]]


def test_server_sink_send_is_not_implemented():
    with pytest.raises(NotImplementedError):
        ServerSink(ServerSettings()).send_batch(["x"])


# ---------------------------------------------------------------------------
# 수명 주기
# ---------------------------------------------------------------------------


def test_shutdown_flushes_every_queued_record(tmp_path: Path):
    configure(file_config(tmp_path))
    log = get_logger("myapp")

    for i in range(500):
        log.info("n", i=i)

    assert [r["fields"]["i"] for r in read_records(tmp_path)] == list(range(500))


def test_reconfigure_keeps_records_in_flight(tmp_path: Path):
    path = file_config(tmp_path)
    configure(path)
    log = get_logger("myapp")

    for i in range(100):
        log.info("n", i=i)
    configure(path)
    log.info("after reload")

    recs = read_records(tmp_path)
    assert [r["fields"].get("i") for r in recs[:100]] == list(range(100))
    assert recs[-1]["msg"] == "after reload"


def test_reconfigure_loses_nothing_logged_concurrently(tmp_path: Path):
    """다른 스레드가 로그를 남기는 도중에 리스너를 갈아 끼워도 레코드가 빠지지 않는다.

    큐를 재구성마다 새로 만들면, 옛 리스너가 멈춘 뒤 옛 큐에 들어간 레코드가 버려진다.
    """

    path = file_config(tmp_path)
    configure(path)
    log = get_logger("myapp")
    count = 3000

    def spam():
        for i in range(count):
            log.info("n", i=i)

    worker = threading.Thread(target=spam)
    worker.start()
    while worker.is_alive():
        configure(path)
    worker.join()

    assert [r["fields"]["i"] for r in read_records(tmp_path)] == list(range(count))


def test_first_emit_configures_from_the_cwd(tmp_path: Path):
    file_config(tmp_path)  # CWD(tmp_path)의 setting.toml

    log = get_logger("myapp")
    assert not trlog._state.configured  # 로거를 얻는 것만으로는 설정을 읽지 않는다
    log.info("auto")

    assert trlog._state.configured
    assert [r["msg"] for r in read_records(tmp_path)] == ["auto"]


def test_no_auto_configure_after_shutdown(tmp_path: Path):
    configure(file_config(tmp_path))
    shutdown()

    get_logger("myapp").info("late")

    assert not trlog._state.configured
