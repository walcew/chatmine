from datetime import UTC, datetime, timedelta

import pytest

from chatmine import core
from chatmine.__main__ import main
from chatmine.core import Account, Session


class _Fake:
    name = "fake-window"

    def __init__(self):
        self.start_ms = None

    def authenticate(self, selector=None, profile=None):
        exp = datetime.now(tz=UTC) + timedelta(hours=1)
        acc = Account(id="a", label="conta", expires_at=exp)
        return Session(account=acc, expires_at=exp, self_id="me", label="conta")

    def list_conversations(self, session, start_time_ms, **kwargs):
        self.start_ms = start_time_ms
        return [{"id": "c1", "type": "group", "topic": "T"}]

    def iter_messages(self, session, conv, start_time_ms, **kwargs):
        times = ["2026-10-03T00:00:00.000Z", "2026-10-02T23:30:00.000Z", "2026-10-01T10:00:00.000Z"]
        for i, t in enumerate([*times, None]):
            yield {
                "id": str(i), "conversationId": "c1", "conversationTopic": "T", "composetime": t,
                "from": {"mri": "x", "displayName": "X"}, "contentText": "m",
            }


@pytest.fixture
def fake():
    p = _Fake()
    core.register(p)
    yield p
    core.registry._REGISTRY.pop(p.name)  # noqa: SLF001


def _ids(out):
    import json

    return [json.loads(line)["id"] for line in (out / "messages.jsonl").read_text().splitlines()]


def test_until_cuts_later_messages_and_summary_shows_window(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    import time

    time.tzset()
    rc = main(["fake-window", "extract", "--since", "2026-10-01", "--until", "2026-10-02",
               "--out", str(tmp_path)])
    assert rc == 0
    # o dia 02 às 23h30 entra; o dia 03 às 00h não
    assert _ids(tmp_path) == ["1", "2", "3"]
    assert fake.start_ms == int(datetime(2026, 10, 1, tzinfo=UTC).timestamp() * 1000)
    assert "2026-10-01T00:00:00+00:00" in (tmp_path / "summary.md").read_text()
    assert "2026-10-02T23:59:59.999999+00:00" in (tmp_path / "summary.md").read_text()


def test_since_with_days_is_usage_error(fake, tmp_path, capsys):
    argv = ["fake-window", "extract", "--since", "2026-10-01", "--days", "3",
            "--out", str(tmp_path)]
    rc = main(argv)
    assert rc != 0
    assert "--since" in capsys.readouterr().err
    assert fake.start_ms is None


def test_no_flags_keeps_seven_days(fake, tmp_path):
    before = datetime.now(tz=UTC)
    main(["fake-window", "extract", "--out", str(tmp_path)])
    got = datetime.fromtimestamp(fake.start_ms / 1000, tz=UTC)
    assert abs((before - timedelta(days=7)) - got) < timedelta(seconds=5)
