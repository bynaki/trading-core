"""trading-core: typed-model task/domain orchestration framework."""

from importlib.metadata import version

from trading_core.definer import (
    DefineError,
    ProcessorDefiner,
    TaskDefiner,
    generator,
    processor,
    task,
)
from trading_core.domain import (
    ClosedConnection,
    Domain,
    DomainError,
    Stage,
    TransmitQueue,
)
from trading_core.model import (
    DataModel,
    ModelError,
    RequestModel,
    Runnable,
    Sequence,
    get_model_generated_origin,
    get_model_id,
    get_model_inst_id,
    get_model_name,
    get_model_type,
    get_module_name,
    set_origin_name,
)

__version__ = version("trading-core")

__all__ = [
    "ClosedConnection",
    "DataModel",
    "DefineError",
    "Domain",
    "DomainError",
    "Stage",
    "ProcessorDefiner",
    "ModelError",
    "RequestModel",
    "Runnable",
    "Sequence",
    "TaskDefiner",
    "TransmitQueue",
    "__version__",
    "get_model_generated_origin",
    "get_model_id",
    "get_model_inst_id",
    "get_model_name",
    "get_model_type",
    "get_module_name",
    "processor",
    "generator",
    "set_origin_name",
    "task",
]
