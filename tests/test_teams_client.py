from datetime import UTC, datetime

import pytest

from chatmine.providers.teams.auth import TeamsTokens
from chatmine.providers.teams.client import ChatSvcClient, ChatSvcError

AMS = "https://eu-api.asm.skype.com/v1/objects/0-neu-d4-abc123/views/imgo"


class _Resp:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.ok = status < 400
        self.content = b"img"
        self.headers = headers or {}


@pytest.fixture
def client(monkeypatch):
    exp = datetime(2030, 1, 1, tzinfo=UTC)
    c = ChatSvcClient(TeamsTokens("a", "SKYPE", "emea", None, None, None, exp, exp))
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return c.next_resp

    monkeypatch.setattr(c._session, "get", fake_get)  # noqa: SLF001
    c.calls = calls
    c.next_resp = _Resp(200, {"Content-Type": "image/png"})
    return c


def test_download_sends_token_only_to_ams_without_following_redirects(client):
    assert client.download(AMS) == (b"img", "image/png")
    url, kwargs = client.calls[0]
    assert url == AMS and kwargs["allow_redirects"] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.example/v1/objects/x/views/imgo",
        "https://asm.skype.com.attacker.example/v1/objects/x/views/imgo",
        "http://eu-api.asm.skype.com/v1/objects/x/views/imgo",
    ],
)
def test_download_refuses_unknown_host_before_any_request(client, url):
    with pytest.raises(ChatSvcError):
        client.download(url)
    assert client.calls == []


def test_download_does_not_follow_redirect(client):
    client.next_resp = _Resp(302, {"Location": "https://attacker.example/x"})
    with pytest.raises(ChatSvcError):
        client.download(AMS)
