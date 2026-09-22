"""프로젝트 전반에서 쓰는 로그 모듈.

설계는 `docs/design.log.md`에 있다. 요약하면:

- `get_logger(__name__)`으로 로거를 얻어 `log.info("메시지", key=value)`처럼 **동기**로 부른다.
  호출은 큐에 넣고 곧바로 반환하며, 실제 출력은 `QueueListener`의 전용 스레드가 맡는다.
- 콘솔·파일·로그서버 싱크는 같은 레코드를 받는다. 무엇을 켤지와 레벨은 `setting.toml`의 `[log]`가
  정한다. 로그서버 싱크는 뼈대만 있고, 켜면 `configure()`가 `LogConfigError`로 실패한다.
- 큐 핸들러는 진짜 루트 로거에 붙는다. `trading_core.*`와 바깥 앱의 로거가 같은 싱크로 모인다.
- 모든 레코드에 `service`/`host`/`pid`/`instance_id`를 실어 여러 서버의 로그를 구분한다.
"""

import asyncio
import atexit
import copy
import json
import logging
import os
import socket
import sys
import threading
import tomllib
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import islice
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler
from pathlib import Path
from queue import SimpleQueue
from types import TracebackType
from typing import Any, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trading_core.exceptions import LogConfigError

SETTINGS_ENV = "TRADING_CORE_SETTINGS"
SETTINGS_FILE = "setting.toml"

type LevelName = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type ExcInfo = bool | BaseException

# 큐 핸들러가 레코드에 심는 속성 이름. 표준 `LogRecord` 속성과 겹치지 않게 접두를 붙인다.
_FIELDS = "tr_fields"
_TASK = "tr_task"
_EXC = "tr_exc"


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConsoleSettings(_Section):
    enabled: bool = True
    level: LevelName = "DEBUG"
    format: Literal["json", "text"] = "text"
    stream: Literal["stdout", "stderr"] = "stderr"


class FileSettings(_Section):
    enabled: bool = False
    level: LevelName = "INFO"
    path: Path = Path("logs/trading_core.jsonl")
    when: str = "midnight"
    backup_count: int = Field(default=14, ge=0)
    utc: bool = True


class ServerSettings(_Section):
    """로그서버 싱크 설정. 전송은 아직 구현되지 않았다."""

    enabled: bool = False
    level: LevelName = "WARNING"
    url: str = ""
    batch_size: int = Field(default=100, ge=1)
    flush_interval: float = Field(default=1.0, gt=0)
    timeout: float = Field(default=3.0, gt=0)
    max_buffer: int = Field(default=10000, ge=1)


class LogSettings(_Section):
    """`setting.toml`의 `[log]` 카테고리."""

    level: LevelName = "INFO"
    service_name: str | None = None
    levels: dict[str, LevelName] = Field(default_factory=dict)
    console: ConsoleSettings = Field(default_factory=ConsoleSettings)
    file: FileSettings = Field(default_factory=FileSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)


def _require_file(path: Path, source: str) -> Path:
    if not path.is_file():
        raise LogConfigError(f"{source} 설정 파일이 없다. - path: {path}")
    return path


def find_settings(path: str | Path | None = None) -> Path | None:
    """설정 파일을 찾는다: 인자 > 환경변수 `TRADING_CORE_SETTINGS` > CWD의 `setting.toml`.

    인자나 환경변수로 **지정했는데** 파일이 없으면 `LogConfigError`다. 아무것도 지정하지 않았고
    CWD에도 없으면 `None`(기본값으로 동작)이다.
    """

    if path is not None:
        return _require_file(Path(path), "인자로 받은")
    env = os.environ.get(SETTINGS_ENV)
    if env:
        return _require_file(Path(env), f"환경변수 {SETTINGS_ENV}가 가리키는")
    candidate = Path.cwd() / SETTINGS_FILE
    return candidate if candidate.is_file() else None


def load_settings(path: str | Path | None = None) -> LogSettings:
    """설정 파일의 `[log]`만 읽어 검증한다. 다른 카테고리는 무시한다."""

    found = find_settings(path)
    if found is None:
        return LogSettings()
    try:
        with found.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise LogConfigError(f"설정 파일을 읽을 수 없다. - path: {found}, {e}") from e
    section = data.get("log", {})
    if not isinstance(section, dict):
        raise LogConfigError(f"[log]는 테이블이어야 한다. - path: {found}")
    try:
        return LogSettings.model_validate(section)
    except ValidationError as e:
        raise LogConfigError(f"[log] 설정이 잘못되었다. - path: {found}\n{e}") from e


# ---------------------------------------------------------------------------
# 발신처 식별
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    """레코드마다 싣는 발신처. `configure()` 때 한 번 계산한다."""

    service: str
    host: str
    pid: int

    @property
    def instance_id(self) -> str:
        return f"{self.service}@{self.host}:{self.pid}"

    @classmethod
    def current(cls, service_name: str | None = None) -> Identity:
        host = socket.gethostname()
        return cls(service=service_name or host, host=host, pid=os.getpid())


# ---------------------------------------------------------------------------
# 레코드 준비 (호출 쪽 스레드)
# ---------------------------------------------------------------------------


def to_jsonable(value: Any) -> Any:
    """`fields` 값을 JSON으로 내보낼 수 있는 값으로 바꾼다. 모르는 값은 `repr()`이다."""

    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, BaseModel):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return repr(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(v) for v in value]
    return repr(value)


def _current_task_name() -> str | None:
    try:
        task = asyncio.current_task()
    except RuntimeError:  # 실행 중인 이벤트 루프가 없다
        return None
    return task.get_name() if task is not None else None


type _SysExcInfo = tuple[type[BaseException], BaseException, TracebackType | None]


def _exc_to_dict(exc_info: _SysExcInfo | tuple[None, None, None] | None) -> dict[str, str] | None:
    if not exc_info or exc_info[1] is None:  # 서드파티가 exc_info=False를 그대로 남기기도 한다
        return None
    exc = exc_info[1]
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(exc)),
    }


class _TrQueueHandler(QueueHandler):
    """레코드를 큐에 넣기 전에, 호출 쪽에서만 알 수 있는 것을 심는다.

    - asyncio 태스크 이름: 리스너 스레드에서는 `current_task()`가 보이지 않는다.
    - 예외 정보와 `fields`: 트레이스백 객체나 가변 값을 스레드 너머로 넘기지 않도록 여기서 굳힌다.

    기본 `prepare()`는 메시지에 트레이스백을 덧붙이므로 쓰지 않는다.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        record = copy.copy(record)
        message = record.getMessage()
        record.__dict__.update(
            {
                _FIELDS: to_jsonable(record.__dict__.get(_FIELDS, {})),
                _TASK: _current_task_name(),
                _EXC: _exc_to_dict(record.exc_info),
            }
        )
        record.message = message
        record.msg = message
        record.args = None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return record


# ---------------------------------------------------------------------------
# 형식 (리스너 스레드)
# ---------------------------------------------------------------------------


def _format_ts(created: float) -> str:
    ts = datetime.fromtimestamp(created, UTC).isoformat(timespec="milliseconds")
    return ts.replace("+00:00", "Z")


def record_to_dict(record: logging.LogRecord, identity: Identity) -> dict[str, Any]:
    extra = record.__dict__
    return {
        "ts": _format_ts(record.created),
        "level": record.levelname,
        "logger": record.name,
        "msg": record.getMessage(),
        "module": record.module,
        "func": record.funcName,
        "line": record.lineno,
        "process": record.process,
        "thread": record.threadName,
        "task": extra.get(_TASK),
        "service": identity.service,
        "host": identity.host,
        "pid": identity.pid,
        "instance_id": identity.instance_id,
        "fields": extra.get(_FIELDS) or {},
        "exc": extra.get(_EXC),
    }


class JsonFormatter(logging.Formatter):
    """레코드 하나를 JSON 한 줄로 만든다. 파일·서버는 항상 이 형식이다."""

    def __init__(self, identity: Identity):
        super().__init__()
        self._identity = identity

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record_to_dict(record, self._identity), ensure_ascii=False, default=repr)


class TextFormatter(logging.Formatter):
    """사람이 읽는 콘솔 형식. 여러 서버의 줄이 섞여도 구분되도록 `[instance_id]`를 넣는다."""

    def __init__(self, identity: Identity):
        super().__init__()
        self._identity = identity

    def format(self, record: logging.LogRecord) -> str:
        d = record_to_dict(record, self._identity)
        line = f"{d['ts']} {d['level']:<5} [{d['instance_id']}] {d['logger']}: {d['msg']}"
        fields: dict[str, Any] = d["fields"]
        if fields:
            line += " {" + ", ".join(f"{k}={v}" for k, v in fields.items()) + "}"
        exc: dict[str, str] | None = d["exc"]
        if exc is not None:
            line += "\n" + exc["traceback"].rstrip()
        return line


# ---------------------------------------------------------------------------
# 싱크
# ---------------------------------------------------------------------------


class _SinkErrorMixin(logging.Handler):
    """싱크 하나의 실패가 다른 싱크를 막지 않게 한다.

    처음 실패만 표준 에러에 알리고, 실패한 레코드는 버린다.
    """

    _warned: bool = False

    def handleError(self, record: logging.LogRecord) -> None:
        if self._warned:
            return
        self._warned = True
        exc = sys.exc_info()[1]
        try:
            sys.stderr.write(
                f"[trading_core.logger] {type(self).__name__} 출력 실패 "
                f"(같은 싱크의 이후 실패는 알리지 않는다): {exc!r}\n"
            )
        except Exception:
            pass


class ConsoleSink(_SinkErrorMixin, logging.StreamHandler[TextIO]):
    pass


class FileSink(_SinkErrorMixin, TimedRotatingFileHandler):
    """JSON Lines 파일. `when`마다 회전하고 `backup_count`개를 보관한다."""

    def __init__(self, settings: FileSettings):
        settings.path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(
            settings.path,
            when=settings.when,
            backupCount=settings.backup_count,
            encoding="utf-8",
            utc=settings.utc,
        )


class ServerSink(_SinkErrorMixin):
    """로그서버 싱크의 뼈대. 배치 버퍼까지만 있고 `send_batch()`는 구현되지 않았다.

    - `batch_size`개가 모이면 `flush()`로 보낸다. 보내지 못한 줄은 버퍼에 남는다.
    - 버퍼가 `max_buffer`를 넘으면 오래된 줄부터 버리고 `dropped`에 센다.
    - `flush_interval`·`timeout`·재시도 정책은 실제 전송을 구현할 때 정한다.
    """

    def __init__(self, settings: ServerSettings):
        super().__init__(level=settings.level)
        self.settings = settings
        self.dropped = 0
        self._buffer: deque[str] = deque(maxlen=settings.max_buffer)

    def send_batch(self, lines: list[str]) -> None:
        raise NotImplementedError("로그서버 전송은 아직 구현되지 않았다.")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            if len(self._buffer) == self._buffer.maxlen:
                self.dropped += 1
            self._buffer.append(line)
            if len(self._buffer) >= self.settings.batch_size:
                self.flush()
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        while self._buffer:
            batch = list(islice(self._buffer, self.settings.batch_size))
            try:
                self.send_batch(batch)
            except Exception:
                return  # 남겨 두고 다음 기회에 다시 보낸다
            for _ in batch:
                self._buffer.popleft()

    def close(self) -> None:
        self.flush()
        super().close()


def _build_sinks(settings: LogSettings, identity: Identity) -> list[logging.Handler]:
    sinks: list[logging.Handler] = []
    try:
        if settings.console.enabled:
            stream = sys.stdout if settings.console.stream == "stdout" else sys.stderr
            console = ConsoleSink(stream)
            console.setLevel(settings.console.level)
            fmt = JsonFormatter if settings.console.format == "json" else TextFormatter
            console.setFormatter(fmt(identity))
            sinks.append(console)
        if settings.file.enabled:
            file = FileSink(settings.file)
            file.setLevel(settings.file.level)
            file.setFormatter(JsonFormatter(identity))
            sinks.append(file)
    except (OSError, ValueError) as e:
        for sink in sinks:
            sink.close()
        raise LogConfigError(f"싱크를 만들 수 없다. - {e}") from e
    return sinks


# ---------------------------------------------------------------------------
# 수명 주기
# ---------------------------------------------------------------------------


@dataclass
class _State:
    lock: threading.RLock = field(default_factory=threading.RLock)
    # 큐와 큐 핸들러는 재구성해도 유지한다. 리스너를 갈아 끼우는 사이에 온 레코드는 큐에 남았다가
    # 새 리스너가 내보낸다.
    queue: SimpleQueue[logging.LogRecord] = field(default_factory=SimpleQueue)
    queue_handler: _TrQueueHandler | None = None
    listener: QueueListener | None = None
    sinks: list[logging.Handler] = field(default_factory=list)
    identity: Identity | None = None
    overridden: list[str] = field(default_factory=list)  # [log.levels]로 레벨을 바꾼 로거 이름
    saved_root_level: int | None = None  # 처음 구성하기 전 루트 레벨(shutdown 때 되돌린다)
    configured: bool = False
    closed: bool = False  # shutdown() 뒤에는 자동 구성하지 않는다
    atexit_registered: bool = False


_state = _State()


def _stop_listener() -> None:
    if _state.listener is not None:
        _state.listener.stop()  # 큐에 이미 들어간 레코드를 모두 내보낸 뒤 멈춘다
        _state.listener = None
    for sink in _state.sinks:
        sink.close()
    _state.sinks = []


def _reset_levels() -> None:
    for name in _state.overridden:
        logging.getLogger(name).setLevel(logging.NOTSET)
    _state.overridden = []


def configure(path: str | Path | None = None) -> None:
    """설정을 읽어 싱크를 구성한다. 이미 구성되어 있으면 리스너를 갈아 끼운다(설정 리로드).

    설정이 잘못되었으면 `LogConfigError`이고, 그때 기존 구성은 그대로 남는다.
    """

    settings = load_settings(path)
    if settings.server.enabled:
        raise LogConfigError(
            "로그서버 전송은 아직 구현되지 않았다. [log.server] enabled를 false로 두어야 한다."
        )
    identity = Identity.current(settings.service_name)
    sinks = _build_sinks(settings, identity)

    with _state.lock:
        _stop_listener()
        _reset_levels()

        root = logging.getLogger()
        if _state.saved_root_level is None:
            _state.saved_root_level = root.level
        root.setLevel(settings.level)
        for name, level in settings.levels.items():
            logging.getLogger(name).setLevel(level)
            _state.overridden.append(name)

        if _state.queue_handler is None:
            _state.queue_handler = _TrQueueHandler(_state.queue)
            root.addHandler(_state.queue_handler)

        listener = QueueListener(_state.queue, *sinks, respect_handler_level=True)
        listener.start()
        _state.listener = listener
        _state.sinks = sinks
        _state.identity = identity
        _state.configured = True
        _state.closed = False

        if not _state.atexit_registered:
            atexit.register(shutdown)
            _state.atexit_registered = True


def shutdown() -> None:
    """큐에 남은 레코드를 모두 내보내고 싱크를 닫는다. 프로세스 종료 때 자동으로 불린다.

    이후의 로그 호출은 자동 구성을 하지 않는다. 다시 쓰려면 `configure()`를 부른다.
    """

    with _state.lock:
        root = logging.getLogger()
        # 큐 핸들러를 먼저 떼어야 멈춘 리스너 뒤로 레코드가 큐에 남지 않는다.
        if _state.queue_handler is not None:
            root.removeHandler(_state.queue_handler)
            _state.queue_handler.close()
            _state.queue_handler = None
        _stop_listener()
        _reset_levels()
        if _state.saved_root_level is not None:
            root.setLevel(_state.saved_root_level)
            _state.saved_root_level = None
        _state.identity = None
        _state.configured = False
        _state.closed = True


def _ensure_configured() -> None:
    if _state.configured or _state.closed:
        return
    with _state.lock:
        if not (_state.configured or _state.closed):
            configure()


# ---------------------------------------------------------------------------
# 공개 로거
# ---------------------------------------------------------------------------


class TrLogger:
    """`logging.Logger`의 얇은 래퍼. 키워드 인자를 레코드의 `fields`로 모은다.

    콘솔·파일·서버 모두 이 메서드 하나로 도달하며, 어디로 갈지는 설정만 정한다. 아직 구성되지
    않았으면 처음 로그를 남길 때 기본 탐색으로 `configure()`한다.
    """

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    @property
    def name(self) -> str:
        return self._logger.name

    def _log(self, level: int, msg: str, exc_info: ExcInfo, fields: dict[str, Any]) -> None:
        _ensure_configured()
        if not self._logger.isEnabledFor(level):
            return
        # stacklevel=3: _log → debug/info/... → 호출부. module/func/line이 호출부를 가리키게 한다.
        self._logger.log(
            level, msg, exc_info=exc_info or None, extra={_FIELDS: fields}, stacklevel=3
        )

    def debug(self, msg: str, /, *, exc_info: ExcInfo = False, **fields: Any) -> None:
        self._log(logging.DEBUG, msg, exc_info, fields)

    def info(self, msg: str, /, *, exc_info: ExcInfo = False, **fields: Any) -> None:
        self._log(logging.INFO, msg, exc_info, fields)

    def warning(self, msg: str, /, *, exc_info: ExcInfo = False, **fields: Any) -> None:
        self._log(logging.WARNING, msg, exc_info, fields)

    def error(self, msg: str, /, *, exc_info: ExcInfo = False, **fields: Any) -> None:
        self._log(logging.ERROR, msg, exc_info, fields)

    def critical(self, msg: str, /, *, exc_info: ExcInfo = False, **fields: Any) -> None:
        self._log(logging.CRITICAL, msg, exc_info, fields)

    def exception(self, msg: str, /, **fields: Any) -> None:
        """`error(..., exc_info=True)`와 같다. `except` 블록 안에서 부른다."""

        self._log(logging.ERROR, msg, True, fields)


def get_logger(name: str) -> TrLogger:
    """`logging.getLogger(name)`을 감싼 `TrLogger`. 접두를 붙이지 않으므로 `__name__`을 넘긴다."""

    return TrLogger(logging.getLogger(name))
