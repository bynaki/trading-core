"""trading-core: typed-model task/domain orchestration framework."""

from importlib.metadata import version

from trading_core.binder import (
    BaseBinder,
    BindPack,
    DependentModelBinder,
    GenerateModelBinder,
    RequestModelBinder,
    initialize,
)
from trading_core.domain import (
    Domain,
    Stage,
    TransmitQueue,
)
from trading_core.exceptions import BindError, ClosedConnection, DomainError
from trading_core.model import (
    BaseReqModel,
    DataModel,
    DependentModel,
    GenerateModel,
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
    "BaseBinder",
    "BaseReqModel",
    "BindError",
    "BindPack",
    "ClosedConnection",
    "DataModel",
    "DependentModel",
    "DependentModelBinder",
    "Domain",
    "DomainError",
    "GenerateModel",
    "GenerateModelBinder",
    "ModelError",
    "Receiver",
    "RequestModel",
    "RequestModelBinder",
    "Runnable",
    "Sender",
    "Sequence",
    "Stage",
    "TransmitQueue",
    "__version__",
    "cast_model",
    "get_model_generated_origin",
    "get_model_id",
    "get_model_inst_id",
    "get_model_name",
    "get_model_type",
    "get_module_name",
    "initialize",
    "set_origin_name",
    "validate_dump",
    "validate_model",
]
