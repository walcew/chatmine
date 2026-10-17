import pytest

from chatmine import core


class _Dummy:
    name = "dummy-provider"


def test_register_and_get():
    d = _Dummy()
    core.register(d)
    assert core.get("dummy-provider") is d
    assert "dummy-provider" in core.names()


def test_get_unknown_raises():
    with pytest.raises(KeyError):
        core.get("inexistente-xyz")


def test_builtin_teams_registered():
    # Importar o pacote de providers registra os embutidos.
    import chatmine.providers  # noqa: F401

    assert "teams" in core.names()
    assert core.get("teams").name == "teams"
