"""数据模型与枚举的内部基类，以及宽容的 JSON 解码。"""

import enum
from types import UnionType
from typing import Any, ClassVar, Self, cast, dataclass_transform, get_args, get_origin

import msgspec

from ._redact import REDACTED

UNKNOWN_MEMBER_NAME = "UNKNOWN"


class OpenIntEnum(enum.IntEnum):
    """容忍未知取值的整数枚举，接口里的整数枚举都继承它。

    未知的整数（`MyEnum(99)` 或 msgspec 解码）得到伪成员：是本枚举的实例，`name` 为 `"UNKNOWN"`，
    `value` 与比较、编码都是原值，但不等于任何已声明的成员。
    """

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        # 只有标准库查不到的值才走到这里，所以 True、1.0 这类与成员值相等的值仍会得到该成员；
        # 这里只防止 bool 变成伪成员。msgspec 解码按 JSON 类型校验，不受影响。
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        # 不缓存进 _value2member_map_：未知取值来自外部输入，缓存会无限增长。
        member = int.__new__(cls, value)
        member._name_ = UNKNOWN_MEMBER_NAME
        member._value_ = value
        return member


class OpenStrEnum(enum.StrEnum):
    """容忍未知取值的字符串枚举，语义与 `OpenIntEnum` 相同。"""

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        if not isinstance(value, str):
            return None
        # 不缓存，理由同 OpenIntEnum。
        member = str.__new__(cls, value)
        member._name_ = UNKNOWN_MEMBER_NAME
        member._value_ = value
        return member


# msgspec 的 kw_only 只对声明它的那个类自己的字段生效，不会被子类继承，所以用元类改默认值。
@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(msgspec.field,))
class _ModelMeta(msgspec.StructMeta):
    # config 原样透传给 msgspec，类型以它为准。
    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        /,
        **config: Any,
    ) -> _ModelMeta:
        config.setdefault("kw_only", True)
        config.setdefault("frozen", True)
        cls = super().__new__(mcs, name, bases, namespace, **config)
        unknown = getattr(cls, "_secret_fields", frozenset[str]()) - set(cls.__struct_fields__)
        if unknown:
            raise TypeError(f"{name}._secret_fields 含有不存在的字段：{sorted(unknown)}")
        return cls


class Model(msgspec.Struct, metaclass=_ModelMeta):
    """所有数据模型的基类。

    模型不可变，字段只能按关键字传入，解码时忽略未知字段。
    `_secret_fields` 里的字段在 `repr()` 与 `__rich_repr__()` 里显示为 `***`，见 `docs/design.md` 约定 7。
    """

    _secret_fields: ClassVar[frozenset[str]] = frozenset()

    # 返回值是任意 JSON 结构，没有比 Any 更精确又好用的类型。
    def to_dict(self) -> dict[str, Any]:
        """转换成与接口 JSON 一一对应的字典，键为接口里的字段名，值只含 JSON 的基本类型。"""
        # 经 JSON 往返而不是 msgspec.to_builtins：后者会把元组等原样留下。
        return msgspec.json.decode(msgspec.json.encode(self))

    def __rich_repr__(self) -> list[tuple[str, Any]]:
        return [
            (name, REDACTED if name in self._secret_fields else value)
            for name, value in super().__rich_repr__()
        ]

    def __repr__(self) -> str:
        if not self._secret_fields:
            return super().__repr__()
        fields = ", ".join(f"{name}={value!r}" for name, value in self.__rich_repr__())
        return f"{type(self).__name__}({fields})"


class RequestModel(Model, omit_defaults=True):
    """由调用方构造、编码进请求体的模型：取默认值的字段不编码，`to_dict()` 里也没有。"""


def decode[T](data: bytes | str, type_: type[T]) -> T:
    """把 JSON 解码成 `type_`；`Model` 里有默认值的字段类型不符时退回默认值，不让整条数据失败。

    `type_` 也可以是 `tuple[模型, ...]`（顶层是数组的响应），元素按 `_clean()` 的规则逐个处理。

    Raises:
        msgspec.DecodeError: 不是合法的 JSON，或必填字段缺失、类型不符。
        RecursionError: 嵌套过深。
    """
    try:
        return msgspec.json.decode(data, type=type_)
    except msgspec.ValidationError:
        target = cast(object, type_)  # 也可能是 tuple[模型, ...] 这样的泛型别名，issubclass 不收
        is_model = isinstance(target, type) and issubclass(target, Model)
        if not is_model and _model_tuple_item(type_) is None:
            raise
    # 只在严格解码失败时才走这条慢路径：先剔除类型不符的可选字段，再严格转换一次。
    return msgspec.convert(_clean(msgspec.json.decode(data), type_), type_)


def _drop_invalid_optional(obj: object, model: type[Model]) -> object:
    """去掉 `obj` 里类型不符的可选字段，嵌套的模型与模型元组逐层处理。"""
    if not isinstance(obj, dict):
        return obj
    values = cast(dict[str, object], obj)
    cleaned = dict(values)
    for info in msgspec.structs.fields(model):
        if info.encode_name not in values:
            continue
        value = cleaned[info.encode_name] = _clean(values[info.encode_name], info.type)
        try:
            msgspec.convert(value, info.type)
        except msgspec.ValidationError:
            if not info.required:
                del cleaned[info.encode_name]
    return cleaned


def _clean(value: object, type_: object) -> object:
    """按 `type_` 清理 `value`：模型逐字段清理；`tuple[模型, ...]` 逐个元素清理，仍不合法的元素单独丢掉。"""
    if get_origin(type_) is UnionType:
        for option in get_args(type_):
            value = _clean(value, option)
        return value
    item_type = _model_tuple_item(type_)
    if item_type is None:
        if isinstance(type_, type) and issubclass(type_, Model):
            return _drop_invalid_optional(value, type_)
        return value
    if not isinstance(value, list):
        return value
    kept: list[object] = []
    for item in cast(list[object], value):
        item = _drop_invalid_optional(item, item_type)
        try:
            msgspec.convert(item, item_type)
        except msgspec.ValidationError:
            continue
        kept.append(item)
    return kept


def _model_tuple_item(type_: object) -> type[Model] | None:
    """`type_` 是 `tuple[M, ...]` 且 `M` 是模型时返回 `M`。"""
    args = get_args(type_)
    if get_origin(type_) is not tuple or len(args) != 2 or args[1] is not Ellipsis:
        return None
    item = args[0]
    return item if isinstance(item, type) and issubclass(item, Model) else None
