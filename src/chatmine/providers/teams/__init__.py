from __future__ import annotations

from collections.abc import Iterator

from ...core.models import Account, Conversation, Message, Session
from ...core.registry import register
from .auth import discover_tenants, get_tokens
from .client import ChatSvcClient, iter_raw_messages, list_recent_conversations
from .normalize import normalize_conversation, normalize_message


class TeamsProvider:
    name = "teams"

    def __init__(self) -> None:
        self._client: ChatSvcClient | None = None

    def discover_accounts(self, profile: str | None = None) -> list[Account]:
        return [
            Account(
                id=t.tenant_id,
                label=t.upn or t.tenant_id,
                expires_at=t.authtoken_exp,
                hint=t.region_hint,
                raw=t,
            )
            for t in discover_tenants(profile or "tfw")
        ]

    def authenticate(self, selector: str | None = None, profile: str | None = None) -> Session:
        tokens = get_tokens(profile or "tfw", tenant=selector)
        self._client = ChatSvcClient(tokens)
        account = Account(
            id=tokens.tenant_id or "",
            label=tokens.upn or tokens.tenant_id or "(sem UPN)",
            expires_at=tokens.authtoken_exp,
            hint=tokens.region,
            raw=tokens,
        )
        return Session(
            account=account,
            expires_at=tokens.skypetoken_exp,
            self_id=f"8:{tokens.skypeid}" if tokens.skypeid else None,
            label=f"{account.label} região={tokens.region} skypeid={tokens.skypeid}",
            raw=tokens,
        )

    def list_conversations(self, session: Session, start_time_ms: int) -> list[Conversation]:
        raw = list_recent_conversations(self._require_client(), start_time_ms)
        return [normalize_conversation(c) for c in raw]

    def iter_messages(
        self,
        session: Session,
        conversation: Conversation,
        start_time_ms: int,
        *,
        include_system: bool = False,
        include_raw: bool = False,
    ) -> Iterator[Message]:
        topic = conversation.get("topic") or ""
        for m in iter_raw_messages(
            self._require_client(),
            conversation["id"],
            start_time_ms=start_time_ms,
            include_system=include_system,
        ):
            yield normalize_message(m, topic, include_raw=include_raw)

    def _require_client(self) -> ChatSvcClient:
        if self._client is None:
            raise RuntimeError("authenticate() precisa ser chamado antes de buscar dados.")
        return self._client


register(TeamsProvider())
