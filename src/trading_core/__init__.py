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
    Receiver,
    RequestModel,
    Runnable,
    Sender,
    Sequence,
    cast_model,
    get_model_generated_origin,
    get_model_id,
    get_model_inst_id,
    get_model_name,
    get_model_type,
    get_module_name,
    set_origin_name,
    validate_dump,
    validate_model,
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
    "cast_model",
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
    "validate_dump",
    "validate_model",
    "Receiver",
    "Sender",
]
