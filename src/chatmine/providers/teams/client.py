from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import requests

from .auth import USER_AGENT, TeamsTokens
from .media import ams_object_id

log = logging.getLogger(__name__)

# Sufixos de ID de conversa:
#   @thread.v2       -> chat em grupo      (queremos)
#   @unq.gbl.spaces  -> chat 1:1           (queremos)
#   @thread.tacv2    -> canal de time      (pulamos por padrão)
#   48:*             -> caixas meta (menções/notificações) — pulamos
CHANNEL_SUFFIX = "@thread.tacv2"
SYSTEM_PREFIXES = ("ThreadActivity/", "Control/", "Event/")
VIEW = "msnp24Equivalent|supportsMessageProperties"


class ChatSvcError(RuntimeError):
    pass


class ChatSvcClient:
    """Wrapper fino sobre o gateway nativo chatsvc do Teams.

    Usa teams.microsoft.com/api/chatsvc/{region} — o gateway público na frente
    do chatservice.skype.com (os hostnames regionais não resolvem publicamente).
    """

    def __init__(self, tokens: TeamsTokens, *, timeout: float = 30.0, max_retries: int = 4):
        self.timeout = timeout
        self.max_retries = max_retries
        self.base = f"https://teams.microsoft.com/api/chatsvc/{tokens.region}/v1/"
        self._session = requests.Session()
        self._session.headers.update(
            {
                "x-skypetoken": tokens.skypetoken,
                "Accept": "application/json",
                "BehaviorOverride": "redirectAs404",
                "User-Agent": USER_AGENT,
            }
        )

    def download(self, url: str) -> tuple[bytes, str | None]:
        """Baixa uma imagem AMS com o skypetoken da sessão.

        A URL vem do conteúdo da mensagem: só hosts AMS recebem o token, e redirects
        não são seguidos (o requests repassaria o header a outro host).
        """
        if not ams_object_id(url):
            raise ChatSvcError(f"refusing to send token to non-AMS url: {url[:120]}")
        resp = self._session.get(
            url, headers={"Accept": "*/*"}, timeout=self.timeout, allow_redirects=False
        )
        if resp.status_code != 200:
            raise ChatSvcError(f"{resp.status_code} em {url}")
        return resp.content, resp.headers.get("Content-Type")

    def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict:
        url = path_or_url if path_or_url.startswith("http") else urljoin(
            self.base, path_or_url.lstrip("/")
        )
        backoff = 1.0
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise ChatSvcError(f"Erro de rede em {url}: {e}") from e
                log.warning("network error (%s), retry in %.1fs", e, backoff)
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                retry_after = float(resp.headers.get("Retry-After", backoff))
                if attempt == self.max_retries:
                    raise ChatSvcError(
                        f"{resp.status_code} persistente em {url}: {resp.text[:200]}"
                    )
                log.warning("status %s, retry in %.1fs", resp.status_code, retry_after)
                time.sleep(min(retry_after, 60.0))
                backoff *= 2
                continue

            if resp.status_code == 401:
                raise ChatSvcError(
                    "401 Unauthorized — o token expirou. "
                    "Abra o Teams para renovar a sessão e rode novamente."
                )
            if not resp.ok:
                raise ChatSvcError(f"{resp.status_code} em {url}: {resp.text[:300]}")
            return resp.json()

        raise ChatSvcError(f"esgotou {self.max_retries} tentativas em {url}")


def _is_chat(conv_id: str) -> bool:
    if conv_id.startswith("48:"):
        return False
    return not conv_id.endswith(CHANNEL_SUFFIX)


def list_recent_conversations(
    client: ChatSvcClient,
    start_time_ms: int,
    *,
    include_channels: bool = False,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    params: dict[str, Any] | None = {
        "pageSize": str(page_size),
        "view": VIEW,
        "startTime": str(start_time_ms),
    }
    url_or_path = "users/ME/conversations"
    out: list[dict[str, Any]] = []
    while True:
        data = client.get(url_or_path, params=params)
        for conv in data.get("conversations", []) or []:
            cid = conv.get("id", "")
            if not include_channels and not _is_chat(cid):
                continue
            out.append(conv)
        nxt = (data.get("_metadata") or {}).get("backwardLink") or ""
        if not nxt:
            return out
        url_or_path = nxt  # a URL de syncState já carrega os params
        params = None


def _composetime_ms(msg: dict[str, Any]) -> int | None:
    v = msg.get("composetime") or msg.get("originalarrivaltime")
    if not v:
        return None
    try:
        s = v.replace("Z", "+00:00")
        # Teams manda 7 dígitos de fração; trunca para microssegundos.
        if "." in s:
            head, _, tail = s.partition(".")
            if "+" in tail:
                frac, tz = tail.split("+", 1)
                tz = "+" + tz
            elif "-" in tail:
                frac, tz = tail.split("-", 1)
                tz = "-" + tz
            else:
                frac, tz = tail, ""
            s = f"{head}.{frac[:6]}{tz}"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _is_system(msg: dict[str, Any]) -> bool:
    mt = msg.get("messagetype") or ""
    return any(mt.startswith(p) for p in SYSTEM_PREFIXES)


def iter_raw_messages(
    client: ChatSvcClient,
    conversation_id: str,
    *,
    start_time_ms: int,
    include_system: bool = False,
    page_size: int = 200,
) -> Iterator[dict[str, Any]]:
    """Mensagens cruas da conversa, da mais nova à mais antiga, até a janela."""
    params: dict[str, Any] | None = {
        "pageSize": str(page_size),
        "view": VIEW,
        "startTime": str(start_time_ms),
    }
    url_or_path = f"users/ME/conversations/{conversation_id}/messages"
    while True:
        data = client.get(url_or_path, params=params)
        messages = data.get("messages") or []
        stop = False
        for m in messages:
            ts = _composetime_ms(m)
            if ts is not None and ts < start_time_ms:
                stop = True
                continue
            if not include_system and _is_system(m):
                continue
            yield m
        if stop:
            return
        meta = data.get("_metadata") or {}
        nxt = meta.get("syncState") or meta.get("backwardLink") or ""
        if not nxt or not messages:
            return
        url_or_path = nxt
        params = None
