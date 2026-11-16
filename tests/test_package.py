from importlib.metadata import version

import pyqbot


def test_version_matches_package_metadata() -> None:
    assert pyqbot.__version__ == version("pyqbot")


def test_every_name_in_all_is_exported() -> None:
    missing = [name for name in pyqbot.__all__ if not hasattr(pyqbot, name)]

    assert missing == []
