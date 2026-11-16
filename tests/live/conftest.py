import os

import pytest


@pytest.fixture(autouse=True)
def block_real_network() -> None:
    """覆盖上层 conftest 的同名兜底：实测就是要访问真实网络。"""


@pytest.fixture
def app_id() -> str:
    return _env("APP_ID")


@pytest.fixture
def app_secret() -> str:
    return _env("APP_SECRET")


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"缺少环境变量 {name}：用 uv run --env-file .env 运行")
    return value
