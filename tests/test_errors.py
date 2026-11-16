import pytest

import pyqbot
from pyqbot._redact import redact, safe_cause


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


def test_payload_error_is_a_separate_kind_of_failure() -> None:
    error = pyqbot.PayloadError("无法解码")

    assert isinstance(error, pyqbot.QQBotError)
    assert not isinstance(error, pyqbot.APIError | pyqbot.NetworkError)


def test_gateway_error_carries_the_close_code() -> None:
    error = pyqbot.GatewayError("网关连接无法恢复：关闭码 4914", err_code=4914)

    assert isinstance(error, pyqbot.QQBotError)
    assert not isinstance(error, pyqbot.NetworkError)
    assert error.err_code == 4914


def test_redact_replaces_every_known_secret() -> None:
    text = "secret=s3cr3t access=t0k-1 t0k-1 s3cr3t/t0k-1"

    assert redact(text, "s3cr3t", "t0k-1", None, "") == "secret=*** access=*** *** ***/***"


def test_redact_replaces_the_longer_secret_first() -> None:
    assert redact("abc-xyz", "abc", "abc-xyz") == "***"


def test_safe_cause_keeps_a_chain_without_secrets() -> None:
    cause = TimeoutError("timed out")

    assert safe_cause(cause, "s3cr3t", None) is cause


def test_safe_cause_drops_a_chain_that_mentions_a_secret_anywhere() -> None:
    outer = OSError("connect failed")
    outer.__cause__ = ValueError("illegal header value: s3cr3t")

    assert safe_cause(outer, "s3cr3t") is None


def test_network_error_is_caught_by_the_base_class_and_keeps_its_cause() -> None:
    cause = TimeoutError("timed out")

    with pytest.raises(pyqbot.QQBotError) as caught:
        raise pyqbot.NetworkError("请求超时") from cause

    assert isinstance(caught.value, pyqbot.NetworkError)
    assert caught.value.__cause__ is cause
    assert caught.value.err_code is None
