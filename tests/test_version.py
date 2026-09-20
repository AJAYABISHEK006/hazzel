import re

import pytest

import hazzel
from hazzel import __main__ as main_mod


def _installed_version():
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("hazzel")
    except PackageNotFoundError:
        return None


def test_source_version_is_parseable():
    assert re.fullmatch(r"\d+\.\d+\.\d+([.-].+)?", hazzel.__version__), hazzel.__version__


def test_installed_metadata_matches_source_version():
    installed = _installed_version()
    if installed is None:
        pytest.skip("hazzel is not installed in this environment")
    assert installed == hazzel.__version__, (
        f"installed metadata says {installed} but source says {hazzel.__version__} — "
        "run `pip install -e . --no-deps` after bumping __version__"
    )


def test_cli_version_reports_source_version():
    assert main_mod._version() == hazzel.__version__
