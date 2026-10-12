import pytest

from infra.scripts.mt5_lab import compile_lab


@pytest.fixture(scope="session")
def mql_binary(tmp_path_factory):
    return compile_lab(tmp_path_factory.mktemp("mql-build"))
