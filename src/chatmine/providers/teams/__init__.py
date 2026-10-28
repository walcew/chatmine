from __future__ import annotations

from collections.abc import Iterator

from ...core.models import Account, Attachment, Conversation, Message, Session
from ...core.registry import register
from .auth import discover_tenants, get_tokens
from .client import ChatSvcClient, iter_raw_messages, list_recent_conversations
from .media import cache_attachment
from .normalize import normalize_conversation, normalize_message


class TeamsProvider:
    name = "teams"

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
            raw=ChatSvcClient(tokens),  # client chatsvc vivo desta sessão
        )

    def list_conversations(self, session: Session, start_time_ms: int) -> list[Conversation]:
        raw = list_recent_conversations(session.raw, start_time_ms)
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
            session.raw,
            conversation["id"],
            start_time_ms=start_time_ms,
            include_system=include_system,
        ):
            yield normalize_message(m, topic, include_raw=include_raw)

    def fetch_attachments(
        self, session: Session, attachments: list[Attachment]
    ) -> list[Attachment]:
        """Baixa as imagens AMS para o cache; SharePoint/OneDrive seguem como link."""
        return [cache_attachment(a, session.raw.download) for a in attachments]


register(TeamsProvider())
