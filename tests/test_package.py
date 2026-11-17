from importlib.metadata import version

import pyqbot


def test_version_matches_package_metadata() -> None:
    assert pyqbot.__version__ == version("pyqbot")


def test_every_name_in_all_is_exported() -> None:
    missing = [name for name in pyqbot.__all__ if not hasattr(pyqbot, name)]

    assert missing == []


def test_frame_decoding_error_stays_internal() -> None:
    # 坏帧由 SDK 自己丢弃，调用方接不到这个异常，导出了只会误导。
    assert "PayloadError" not in pyqbot.__all__
    assert not hasattr(pyqbot, "PayloadError")


def test_handler_type_is_public() -> None:
    # 调用方给自己的处理函数集合标注类型时要用到它。
    async def echo(message: pyqbot.C2CMessage) -> None: ...

    handlers: list[pyqbot.Handler[pyqbot.C2CMessage]] = [echo]

    assert handlers == [echo]
