"""互动事件的接口。"""

from .._http import HTTP, path_segment
from .._models.interaction import Interaction, InteractionResult


class Interactions:
    """互动事件（`INTERACTION_CREATE`）相关的接口，经 `client.interactions` 使用。"""

    def __init__(self, http: HTTP) -> None:
        self._http = http

    async def ack(
        self,
        interaction: str | Interaction,
        *,
        code: InteractionResult = InteractionResult.SUCCESS,
    ) -> None:
        """回应一次互动，告诉平台已经处理，用户那边随之结束等待。

        只有回调按钮与快捷菜单（`InteractionType.INLINE_KEYBOARD`、`CALLBACK_COMMAND`）需要回应，
        其它类型回应了也不报错。实测客户端只等约 1 秒（文档写 3 秒）：晚了接口照样成功，用户却看到
        「请求第三方失败」；重复回应也不报错。SDK 不自动回应。

        对应官方接口 `PUT /interactions/{interaction_id}`。

        Args:
            interaction: 收到的 `Interaction`，或它的 `id`（事件体里的 `id`，不是 `event_id`）。
            code: 处理结果，客户端据此给用户提示。

        Raises:
            APIError: 平台拒绝，例如互动已过期或已回应过。
            NetworkError: 没有拿到平台的响应。
            ValueError: 互动 ID 为空。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.interactions.ack(interaction, code=pyqbot.InteractionResult.NO_PERMISSION)
            ```
        """
        interaction_id = interaction if isinstance(interaction, str) else interaction.id
        path = f"/interactions/{path_segment(interaction_id, 'interaction_id')}"
        # 文档的响应是 {}，没有可用的内容。
        await self._http.request("PUT", path, type_=None, json={"code": code})
