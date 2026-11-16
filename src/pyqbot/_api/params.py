"""接口参数的规范化：时刻与时长、单个或多个 ID。约定见 `docs/design.md`「时间与批量参数」。"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    """当前时刻（UTC）；测试里替换它来固定时钟。"""
    return datetime.now(UTC)


def deadline(value: datetime | timedelta, name: str) -> datetime:
    """把时刻或从现在起算的时长换成 UTC 时刻，不足一秒的部分向上取整。

    Raises:
        ValueError: `datetime` 没有时区，或 `timedelta` 不是正数。
    """
    if isinstance(value, timedelta):
        if value <= timedelta(0):
            raise ValueError(f"{name} 必须是正的时长：{value!r}")
        value = utc_now() + value
    elif value.utcoffset() is None:
        # 没有时区的时刻没法知道调用方指的是哪个时区，平台会按自己的理解解读。
        raise ValueError(f"{name} 必须带时区，例如 datetime.now(UTC) + timedelta(hours=1)")
    # 转成 UTC：带秒级偏移的时区（如 +00:00:30）直接输出不是合法的 RFC3339。
    value = value.astimezone(UTC)
    if value.microsecond:
        # 截止时刻晚不到一秒无害，截掉小数则可能早于现在。
        value = value.replace(microsecond=0) + timedelta(seconds=1)
    return value


def rfc3339(value: datetime | timedelta, name: str) -> str:
    """编码成 UTC 的 RFC3339 字符串，规则同 `deadline()`。"""
    return deadline(value, name).isoformat(timespec="seconds")


def unix_seconds(value: datetime | timedelta, name: str) -> str:
    """编码成 Unix 秒的十进制字符串，规则同 `deadline()`。"""
    return str(int(deadline(value, name).timestamp()))


def str_list(value: str | Iterable[str]) -> list[str]:
    """单个字符串当作一个元素；否则展开成列表（`str` 本身也可迭代，不这样处理会被拆成单个字符）。"""
    return [value] if isinstance(value, str) else list(value)
