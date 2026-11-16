import pytest

import pyqbot


def test_base_error_carries_message_only_by_default() -> None:
    error = pyqbot.QQBotError("出错了")

    assert error.message == "出错了"
    assert error.err_code is None
    assert error.trace_id is None
    assert str(error) == "出错了"


def test_str_includes_known_err_code_and_trace_id() -> None:
    error = pyqbot.QQBotError("回复消息msg_id已过期", err_code=40034005, trace_id="4a8a6156")

    assert str(error) == "回复消息msg_id已过期（err_code=40034005, trace_id=4a8a6156）"


def test_str_skips_details_that_are_unknown() -> None:
    error = pyqbot.QQBotError("appid invalid", err_code=100007)

    assert str(error) == "appid invalid（err_code=100007）"


def test_api_error_adds_status_code() -> None:
    error = pyqbot.APIError("校验 token 未通过", status_code=401, err_code=11243, trace_id="4a8a")

    assert isinstance(error, pyqbot.QQBotError)
    assert (error.status_code, error.err_code, error.trace_id) == (401, 11243, "4a8a")


def test_network_error_is_caught_by_the_base_class_and_keeps_its_cause() -> None:
    cause = TimeoutError("timed out")

    with pytest.raises(pyqbot.QQBotError) as caught:
        raise pyqbot.NetworkError("请求超时") from cause

    assert isinstance(caught.value, pyqbot.NetworkError)
    assert caught.value.__cause__ is cause
    assert caught.value.err_code is None
