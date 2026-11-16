"""数据模型与枚举的内部基类，以及宽容的 JSON 解码。"""

import enum
from typing import Any, ClassVar, Self, cast, dataclass_transform, get_args

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


def decode[T](data: bytes | str, type_: type[T]) -> T:
    """把 JSON 解码成 `type_`；`Model` 里有默认值的字段类型不符时退回默认值，不让整条数据失败。

    Raises:
        msgspec.DecodeError: 不是合法的 JSON，或必填字段缺失、类型不符。
        RecursionError: 嵌套过深。
    """
    try:
        return msgspec.json.decode(data, type=type_)
    except msgspec.ValidationError:
        if not issubclass(type_, Model):
            raise
    # 只在严格解码失败时才走这条慢路径：先剔除类型不符的可选字段，再严格转换一次。
    return msgspec.convert(_drop_invalid_optional(msgspec.json.decode(data), type_), type_)


def _drop_invalid_optional(obj: object, model: type[Model]) -> object:
    """去掉 `obj` 里类型不符的可选字段，嵌套的模型逐层处理。"""
    if not isinstance(obj, dict):
        return obj
    values = cast(dict[str, object], obj)
    cleaned = dict(values)
    for info in msgspec.structs.fields(model):
        if info.encode_name not in values:
            continue
        value = values[info.encode_name]
        for nested in get_args(info.type) or (info.type,):
            if isinstance(nested, type) and issubclass(nested, Model):
                value = cleaned[info.encode_name] = _drop_invalid_optional(value, nested)
        try:
            msgspec.convert(value, info.type)
        except msgspec.ValidationError:
            if not info.required:
                del cleaned[info.encode_name]
    return cleaned
