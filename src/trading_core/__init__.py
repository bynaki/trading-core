"""trading-core: typed-model task/domain orchestration framework."""

from importlib.metadata import version

from trading_core.binder import (
    BaseBinder,
    BindPack,
    DerivedBinder,
    SessionBinder,
    SourceBinder,
    initialize,
)
from trading_core.domain import (
    Domain,
    Subscription,
)
from trading_core.exceptions import BindError, ChannelClosed, DomainError
from trading_core.model import (
    BaseRequest,
    DataModel,
    DerivedRequest,
    ModelError,
    Pipeline,
    Receiver,
    Runnable,
    Sender,
    SessionRequest,
    SourceRequest,
    cast_model,
    get_instance_id,
    get_model_created_by,
    get_model_id,
    get_model_name,
    get_model_type,
    get_model_uid,
    get_module_name,
    load_model,
    parse_dump,
    set_instance_id,
)
from trading_core.routing import Channel

__version__ = version("trading-core")

__all__ = [
    "BaseBinder",
    "BaseRequest",
    "BindError",
    "BindPack",
    "Channel",
    "ChannelClosed",
    "DataModel",
    "DerivedBinder",
    "DerivedRequest",
    "Domain",
    "DomainError",
    "ModelError",
    "Pipeline",
    "Receiver",
    "Runnable",
    "Sender",
    "SessionBinder",
    "SessionRequest",
    "SourceBinder",
    "SourceRequest",
    "Subscription",
    "__version__",
    "cast_model",
    "get_instance_id",
    "get_model_created_by",
    "get_model_id",
    "get_model_name",
    "get_model_type",
    "get_model_uid",
    "get_module_name",
    "initialize",
    "load_model",
    "parse_dump",
    "set_instance_id",
]
