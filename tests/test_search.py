import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from chatmine import core
from chatmine.__main__ import main
from chatmine.core import Account, Session


def _msg(mid, conv, t, text, *, sender=("x@ex.com", "Xavier"), attachments=None, **extra):
    return {
        "id": mid, "conversationId": conv["id"], "conversationTopic": conv["topic"],
        "composetime": t, "from": {"mri": sender[0], "displayName": sender[1]},
        "messagetype": "Text", "contentHtml": "<p>html</p>", "contentText": text,
        "isEdited": False, "parentMessageId": None, "reactions": [],
        "attachments": attachments or [], "raw": {"x": 1}, **extra,
    }


class _Fake:
    def __init__(self, name, convs, msgs, *, fail=None):
        self.name = name
        self.convs = convs
        self.msgs = msgs  # conv id -> lista de mensagens, da mais nova para a mais antiga
        self.fail = fail
        self.calls = []

    def authenticate(self, selector=None, profile=None):
        self.calls.append(("auth", selector, profile))
        if self.fail:
            raise self.fail
        exp = datetime.now(tz=UTC) + timedelta(hours=1)
        acc = Account(id="a", label=f"conta-{self.name}", expires_at=exp)
        return Session(account=acc, expires_at=exp, self_id="me@ex.com", label="conta")

    def list_conversations(self, session, start_time_ms, **kwargs):
        self.calls.append(("list", kwargs))
        return self.convs

    def iter_messages(self, session, conv, start_time_ms, **kwargs):
        yield from self.msgs.get(conv["id"], [])


GROUP = {"id": "g1", "type": "group", "topic": "Solicitação de Cotação"}
DM = {"id": "d1", "type": "oneOnOne", "topic": "Bia"}
PDF = {
    "name": "proposta-final.pdf", "contentType": "application/pdf",
    "contentUrl": "file:///tmp/proposta-final.pdf", "path": "/tmp/proposta-final.pdf",
    "url": None, "available": True,
}


def _base_msgs():
    return {
        "g1": [
            _msg("g5", GROUP, "2026-10-10T15:00:00.000Z", "depois de tudo"),
            _msg("g4", GROUP, "2026-10-10T14:00:00.000Z", "Segue o arquivo",
                 attachments=[PDF], sender=("me@ex.com", "Eu")),
            _msg("g3", GROUP, "2026-10-10T13:00:00.000Z", "A COTAÇÃO chegou"),
            _msg("g2", GROUP, "2026-10-10T12:00:00.000Z", "bom dia"),
            _msg("g1", GROUP, "2026-10-10T11:00:00.000Z", "oi"),
        ],
        "d1": [
            _msg("d2", DM, "2026-10-09T10:00:00.000Z", "falou com o Zé?",
                 sender=("bia@ex.com", "Beatriz Ávila")),
            _msg("d1", DM, "2026-10-01T10:00:00.000Z", "antigo", sender=("bia@ex.com", "Beatriz")),
        ],
    }


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def register():
    added = []

    def _add(p):
        core.register(p)
        added.append(p.name)
        return p

    yield _add
    for name in added:
        core.registry._REGISTRY.pop(name)  # noqa: SLF001


@pytest.fixture
def fake(register):
    return register(_Fake("fake-a", [GROUP, DM], _base_msgs()))


WINDOW = ["--since", "2026-10-05", "--until", "2026-10-10"]


def _search(capsys, *argv):
    rc = main(["search", *argv])
    out = capsys.readouterr()
    return rc, json.loads(out.out) if out.out else None, out.err


def _ids(env):
    return [r["id"] for r in env["results"]]


def test_match_ignores_case_and_accents(fake, capsys):
    rc, env, _ = _search(capsys, "cotacao chegou", "--provider", "fake-a", *WINDOW)
    assert rc == 0
    assert _ids(env) == ["g3"]
    assert env["query"] == "cotacao chegou"
    assert env["providers"] == ["fake-a"]
    assert env["window"] == {"since": "2026-10-05T00:00:00+00:00",
                             "until": "2026-10-10T23:59:59+00:00"}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("chegou", ["g3"]),  # texto
        ("solicitacao", ["g5", "g4", "g3", "g2", "g1"]),  # título da conversa
        ("beatriz avila", ["d2"]),  # nome do remetente
        ("bia@ex", ["d2"]),  # endereço do remetente
        ("PROPOSTA-FINAL", ["g4"]),  # nome do anexo
    ],
)
def test_searched_fields(fake, capsys, query, expected):
    _, env, _ = _search(capsys, query, "--provider", "fake-a", *WINDOW, "--limit", "10")
    assert _ids(env) == expected


def test_from_filter(fake, capsys):
    _, env, _ = _search(capsys, "o", "--provider", "fake-a", *WINDOW, "--from", "AVILA")
    assert _ids(env) == ["d2"]


def test_conversation_filter_by_title_or_id(fake, capsys):
    _, env, _ = _search(capsys, "o", "--provider", "fake-a", *WINDOW, "--conversation", "bia")
    assert _ids(env) == ["d2"]
    _, env, _ = _search(capsys, "o", "--provider", "fake-a", *WINDOW, "--conversation", "g1")
    assert _ids(env) == ["g5", "g4", "g3", "g2", "g1"]


def test_has_attachments_filter(fake, capsys):
    _, env, _ = _search(capsys, "", "--provider", "fake-a", *WINDOW, "--has-attachments")
    assert _ids(env) == ["g4"]


def test_window_cuts_both_ends(fake, capsys):
    # o "antigo" de 01/10 fica antes do --since; nada depois de 10/10 23:59:59
    _, env, _ = _search(capsys, "", "--provider", "fake-a", "--since", "2026-10-09",
                        "--until", "2026-10-10T13:30:00", "--limit", "10")
    assert _ids(env) == ["g3", "g2", "g1", "d2"]


def test_until_date_only_includes_whole_day(fake, capsys):
    _, env, _ = _search(capsys, "depois", "--provider", "fake-a", "--since", "2026-10-10",
                        "--until", "2026-10-10")
    assert _ids(env) == ["g5"]


def test_days_counts_back_from_now(register, capsys):
    now = datetime.now(tz=UTC)
    recent = (now - timedelta(days=1)).isoformat()
    old = (now - timedelta(days=3)).isoformat()
    register(_Fake("fake-days", [DM], {"d1": [_msg("new", DM, recent, "x"),
                                              _msg("old", DM, old, "x")]}))
    _, env, _ = _search(capsys, "x", "--provider", "fake-days", "--days", "2")
    assert _ids(env) == ["new"]
    _, env, _ = _search(capsys, "x", "--provider", "fake-days")  # padrão 7 dias
    assert _ids(env) == ["new", "old"]


def test_since_with_days_is_usage_error(fake, capsys):
    rc, env, err = _search(capsys, "x", "--provider", "fake-a", "--since", "2026-10-01",
                           "--days", "3")
    assert rc != 0
    assert env is None
    assert "--since" in err
    assert fake.calls == []


def test_unknown_provider_is_usage_error(fake, capsys):
    rc, env, err = _search(capsys, "x", "--provider", "fake-a,nope")
    assert rc != 0
    assert "nope" in err


def test_context_is_chronological_and_reduced(fake, capsys):
    _, env, _ = _search(capsys, "chegou", "--provider", "fake-a", *WINDOW)
    ctx = env["results"][0]["context"]
    assert [c["id"] for c in ctx] == ["g1", "g2", "g4", "g5"]
    assert ctx[2] == {
        "id": "g4", "time": "2026-10-10T14:00:00+00:00", "from": "Eu <me@ex.com>",
        "isSelf": True, "text": "Segue o arquivo", "attachments": ["proposta-final.pdf"],
    }
    assert "context" not in ctx[0]


def test_context_size_and_zero(fake, capsys):
    _, env, _ = _search(capsys, "chegou", "--provider", "fake-a", *WINDOW, "--context", "1")
    assert [c["id"] for c in env["results"][0]["context"]] == ["g2", "g4"]
    _, env, _ = _search(capsys, "chegou", "--provider", "fake-a", *WINDOW, "--context", "0")
    assert env["results"][0]["context"] == []


def test_order_newest_first_across_providers_limit_total_truncated(fake, register, capsys):
    other = {"id": "o1", "type": "group", "topic": "Outro"}
    register(_Fake("fake-b", [other], {"o1": [_msg("b1", other, "2026-10-10T13:30:00Z", "oi")]}))
    _, env, _ = _search(capsys, "o", "--provider", "fake-a,fake-b", *WINDOW, "--limit", "3")
    assert _ids(env) == ["g5", "g4", "b1"]
    assert env["total"] == 7
    assert env["truncated"] is True
    _, env, _ = _search(capsys, "o", "--provider", "fake-a,fake-b", *WINDOW, "--limit", "7")
    assert env["truncated"] is False


def test_result_shape_and_attachment(fake, capsys):
    _, env, _ = _search(capsys, "segue", "--provider", "fake-a", *WINDOW, "--context", "0")
    assert env["results"] == [{
        "provider": "fake-a", "account": "conta-fake-a",
        "conversation": {"id": "g1", "title": "Solicitação de Cotação", "type": "group"},
        "id": "g4", "time": "2026-10-10T14:00:00+00:00", "from": "Eu <me@ex.com>",
        "isSelf": True, "text": "Segue o arquivo",
        "attachments": [{"name": "proposta-final.pdf", "type": "application/pdf",
                         "path": "/tmp/proposta-final.pdf", "url": None, "available": True}],
        "context": [],
    }]


def test_to_and_cc_when_present(register, capsys):
    m = _msg("m1", DM, "2026-10-09T10:00:00Z", "x",
             to=[{"mri": "a@ex.com", "displayName": "Ana"}], cc=[])
    register(_Fake("fake-mail", [DM], {"d1": [m]}))
    _, env, _ = _search(capsys, "x", "--provider", "fake-mail", *WINDOW)
    assert env["results"][0]["to"] == ["Ana <a@ex.com>"]
    assert env["results"][0]["cc"] == []


def test_teams_like_sender_shows_only_name(register, capsys):
    m = _msg("t1", DM, "2026-10-09T10:00:00Z", "x", sender=("8:orgid:abc", "Carla"))
    register(_Fake("fake-teams", [DM], {"d1": [m]}))
    _, env, _ = _search(capsys, "x", "--provider", "fake-teams", *WINDOW)
    assert env["results"][0]["from"] == "Carla"
    assert env["results"][0]["isSelf"] is False


def test_failing_provider_goes_to_errors_and_others_continue(fake, register, capsys):
    register(_Fake("fake-bad", [], {}, fail=RuntimeError("session expired")))
    rc, env, err = _search(capsys, "chegou", "--provider", "fake-bad,fake-a", *WINDOW)
    assert rc == 0
    assert _ids(env) == ["g3"]
    assert env["errors"] == [{"provider": "fake-bad", "reason": "session expired",
                              "hint": "Abra o app para renovar a sessão e rode novamente"}]
    assert "fake-bad" in err  # aviso no stderr, stdout continua JSON puro


def test_all_providers_failing_exits_nonzero(register, capsys):
    register(_Fake("fake-bad", [], {}, fail=FileNotFoundError("não instalado")))
    rc, env, _ = _search(capsys, "x", "--provider", "fake-bad")
    assert rc != 0
    assert env["errors"][0]["provider"] == "fake-bad"
    assert env["results"] == []


def test_account_and_profile_are_passed_through(fake, capsys):
    _search(capsys, "x", "--provider", "fake-a", "--account", "acme", "--profile", "tfw")
    assert fake.calls[0] == ("auth", "acme", "tfw")


def test_include_bulk_is_passed_to_providers(fake, capsys):
    _search(capsys, "x", "--provider", "fake-a")
    _search(capsys, "x", "--provider", "fake-a", "--include-bulk")
    lists = [kw for call, kw, *_ in fake.calls if call == "list"]
    assert lists == [{"include_bulk": False}, {"include_bulk": True}]
