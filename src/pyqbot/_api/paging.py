"""分页接口的异步迭代：接口方法只写「怎么取一页」，翻页由 `paginate()` 负责。用法见 `docs/design.md`。"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Page[T, C]:
    """取到的一页。

    Attributes:
        items: 这一页的条目。
        next: 取下一页要用的游标（`cursor`、`cookie`、偏移量等，类型随接口而定）；`None` 表示没有下一页。
    """

    items: Iterable[T]
    next: C | None = None


async def paginate[T, C](fetch: Callable[[C | None], Awaitable[Page[T, C]]]) -> AsyncIterator[T]:
    """依次产出每一页的条目，直到没有下一页。

    `fetch(None)` 取第一页，之后每次传入上一页的 `next`。`next` 为 `None`、空串，或与刚用过的游标相同
    （防止平台反复给出同一个游标时无限循环）时结束。
    """
    cursor: C | None = None
    while True:
        page = await fetch(cursor)
        for item in page.items:
            yield item
        if page.next is None or page.next == "" or page.next == cursor:
            return
        cursor = page.next
