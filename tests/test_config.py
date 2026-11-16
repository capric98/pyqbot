import pytest

import pyqbot


def test_defaults_point_at_the_official_api() -> None:
    config = pyqbot.Config(app_id="app-id", app_secret="app-secret")

    assert config.base_url == "https://api.bot.qq.com"
    assert config.timeout == 30.0


@pytest.mark.parametrize(
    ("given", "normalized"),
    [
        ("https://sandbox.example.com", "https://sandbox.example.com"),
        ("https://sandbox.example.com/", "https://sandbox.example.com"),
        ("http://127.0.0.1:8080/proxy/", "http://127.0.0.1:8080/proxy"),
    ],
)
def test_base_url_can_be_overridden_and_loses_its_trailing_slash(
    given: str, normalized: str
) -> None:
    config = pyqbot.Config(app_id="app-id", app_secret="app-secret", base_url=given)

    assert config.base_url == normalized


def test_repr_does_not_leak_the_secret() -> None:
    config = pyqbot.Config(app_id="app-id", app_secret="app-secret")

    assert "app-secret" not in repr(config)
    assert "app-id" in repr(config)


@pytest.mark.parametrize(
    ("app_id", "app_secret", "field"),
    [("", "app-secret", "app_id"), ("app-id", "", "app_secret")],
)
def test_empty_credentials_are_rejected(app_id: str, app_secret: str, field: str) -> None:
    with pytest.raises(ValueError, match=f"{field} 不能为空"):
        pyqbot.Config(app_id=app_id, app_secret=app_secret)


@pytest.mark.parametrize(
    "base_url", ["", "api.bot.qq.com", "ftp://api.bot.qq.com", "https://", "http://[::1"]
)
def test_base_url_must_be_a_full_http_url(base_url: str) -> None:
    with pytest.raises(ValueError, match="base_url 必须是完整的"):
        pyqbot.Config(app_id="app-id", app_secret="app-secret", base_url=base_url)


@pytest.mark.parametrize("timeout", [0, -1.0, float("nan")])
def test_timeout_must_be_positive(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout 必须大于 0"):
        pyqbot.Config(app_id="app-id", app_secret="app-secret", timeout=timeout)
