"""trading-core: typed-model task/domain orchestration framework."""

from importlib.metadata import version

from trading_core.definer import (
    DomainContext,
    DomainError,
    DomainModel,
    TaskModel,
    domain,
    task,
)
from trading_core.model import (
    DataModel,
    ModelError,
    RequestModel,
    Runnable,
    Sequence,
    set_origin_name,
)

__version__ = version("trading-core")

__all__ = [
    "DataModel",
    "DomainContext",
    "DomainError",
    "DomainModel",
    "ModelError",
    "RequestModel",
    "Runnable",
    "Sequence",
    "TaskModel",
    "__version__",
    "domain",
    "set_origin_name",
    "task",
]
