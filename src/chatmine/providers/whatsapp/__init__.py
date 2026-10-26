from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ...core.models import Account, Conversation, Message, Session
from ...core.registry import register
from .store import (
    CONVERSATIONS_SQL,
    MESSAGES_SQL,
    SELF_ID,
    SYSTEM_TYPES,
    connect,
    container_root,
    load_names,
    ms_to_apple,
    normalize_conversation,
    normalize_message,
)

# Banco local não expira; o pipeline só exige uma data.
NEVER = datetime.max.replace(tzinfo=UTC)


@dataclass(frozen=True)
class LocalStore:
    root: Path
    names: dict[str, str]


class WhatsAppProvider:
    name = "whatsapp"

    def discover_accounts(self, profile: str | None = None) -> list[Account]:
        root = container_root(profile)
        if not (root / "ChatStorage.sqlite").exists():
            return []
        label = f"WhatsApp {profile or 'personal'} (local)"
        return [Account(id=profile or "personal", label=label, expires_at=NEVER, hint=str(root))]

    def authenticate(self, selector: str | None = None, profile: str | None = None) -> Session:
        # `selector` não se aplica: o banco local é de uma única conta.
        accounts = self.discover_accounts(profile)
        if not accounts:
            raise FileNotFoundError(f"WhatsApp Desktop não encontrado em {container_root(profile)}")
        account = accounts[0]
        root = container_root(profile)
        return Session(
            account=account,
            expires_at=NEVER,
            self_id=SELF_ID,
            label=account.label,
            raw=LocalStore(root=root, names=load_names(root)),
        )

    def list_conversations(self, session: Session, start_time_ms: int) -> list[Conversation]:
        with closing(connect(session.raw.root / "ChatStorage.sqlite")) as conn:
            rows = conn.execute(CONVERSATIONS_SQL, (ms_to_apple(start_time_ms),)).fetchall()
        return [normalize_conversation(dict(r)) for r in rows]

    def iter_messages(
        self,
        session: Session,
        conversation: Conversation,
        start_time_ms: int,
        *,
        include_system: bool = False,
        include_raw: bool = False,
    ) -> Iterator[Message]:
        store: LocalStore = session.raw
        with closing(connect(store.root / "ChatStorage.sqlite")) as conn:
            rows = conn.execute(
                MESSAGES_SQL, (conversation["id"], ms_to_apple(start_time_ms))
            ).fetchall()
        for r in rows:
            row = dict(r)
            if not include_system and row["ZMESSAGETYPE"] in SYSTEM_TYPES:
                continue
            yield normalize_message(
                row, conversation, store.names, store.root / "Message", include_raw=include_raw
            )


register(WhatsAppProvider())
