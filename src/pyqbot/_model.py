"""数据模型的内部基类。"""

from typing import Any, dataclass_transform

import msgspec


# msgspec 的 kw_only 只对声明它的那个类自己的字段生效，不会被子类继承；
# 用元类改掉默认值，每个模型才不必（也不会忘记）重复声明。
# dataclass_transform 让类型检查器按同样的默认值理解模型。
@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(msgspec.field,))
class _ModelMeta(msgspec.StructMeta):
    # config 原样透传 msgspec 的类定义选项，类型以 msgspec 为准，这里不重复声明。
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
        return super().__new__(mcs, name, bases, namespace, **config)


class Model(msgspec.Struct, metaclass=_ModelMeta):
    """所有数据模型的基类。

    模型不可变，字段只能按关键字传入。解码时遇到未知字段会直接忽略，
    上游新增字段不会导致报错。

    msgspec 只是内部实现，不属于公共接口：对外需要的能力都在本类上提供方法。
    """

    # 返回值是任意 JSON 结构，没有比 Any 更精确又好用的类型。
    def to_dict(self) -> dict[str, Any]:
        """转换成与接口 JSON 一一对应的字典，键为接口里的字段名。

        嵌套的模型会一并转换，枚举转成它的值，时间转成 ISO 8601 字符串。

        Returns:
            只含 `dict`、`list`、`str`、`int`、`float`、`bool`、`None` 的字典。
        """
        # 经 JSON 往返而不是 msgspec.to_builtins：后者会把元组等原样留下，结果就不是纯 JSON 结构了。
        return msgspec.json.decode(msgspec.json.encode(self))
