import pytest

from infra.scripts.mt5_lab import compile_lab, compile_native


@pytest.fixture(scope="session")
def mql_binary(tmp_path_factory):
    return compile_lab(tmp_path_factory.mktemp("mql-build"))


@pytest.fixture(scope="session")
def native_binary(tmp_path_factory):
    return compile_native(tmp_path_factory.mktemp("mql-native-build"))
