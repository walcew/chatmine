from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ...core.models import Account, Conversation, Message, Session
from ...core.registry import register
from .store import (
    EXCLUDED_MAILBOXES,
    MESSAGES_SQL,
    RECIPIENT_CC,
    RECIPIENT_TO,
    RECIPIENTS_SQL,
    account_labels,
    bodies,
    clean_subject,
    connect,
    data_dir,
    dedup,
    emlx_path,
    epoch_to_iso,
    load_mailboxes,
    mailbox_account,
    mailbox_dir,
    mailbox_name,
    message_filter,
    read_emlx,
    sender,
    sent_senders,
)

# Banco local não expira; o pipeline só exige uma data.
NEVER = datetime.max.replace(tzinfo=UTC)


@dataclass(frozen=True)
class MailStore:
    data: Path
    mailboxes: dict[int, Path]  # só as pastas das contas escolhidas, sem Lixeira e Spam


def _index(data: Path) -> Path:
    return data / "MailData" / "Envelope Index"


class MailProvider:
    name = "mail"

    def _scan(self) -> tuple[Path, dict[int, str], list[Account], set[str]]:
        data = data_dir()
        labels = account_labels(data)
        with closing(connect(_index(data))) as conn:
            mailboxes = load_mailboxes(conn)
            senders = sent_senders(conn, mailboxes)
        accounts = []
        for uuid in sorted({mailbox_account(url) for url in mailboxes.values()}):
            label = labels.get(uuid) or next(iter(senders.get(uuid, [])), uuid)
            accounts.append(Account(id=uuid, label=label, expires_at=NEVER, hint=str(data / uuid)))
        # Endereços próprios: o e-mail de cada conta e quem aparece como remetente nos enviados.
        own = {a.label.lower() for a in accounts if "@" in a.label}
        own.update(addr for addrs in senders.values() for addr in addrs)
        return data, mailboxes, accounts, own

    def discover_accounts(self, profile: str | None = None) -> list[Account]:
        # `profile` não se aplica: o Mail tem uma única instalação.
        try:
            return self._scan()[2]
        except FileNotFoundError:
            return []

    def authenticate(self, selector: str | None = None, profile: str | None = None) -> Session:
        data, mailboxes, accounts, own = self._scan()
        chosen = accounts
        if selector:
            wanted = selector.lower()
            chosen = [a for a in accounts if wanted in (a.id.lower(), a.label.lower())]
            if not chosen:
                available = ", ".join(a.label for a in accounts) or "(nenhuma)"
                raise ValueError(
                    f"Conta {selector!r} não encontrada no Mail. Disponíveis: {available}"
                )
        if not chosen:
            raise FileNotFoundError("Nenhuma conta encontrada no Apple Mail")
        ids = {a.id for a in chosen}
        account = chosen[0] if len(chosen) == 1 else Account(
            id="all", label=", ".join(a.label for a in chosen), expires_at=NEVER, hint=str(data)
        )
        store = MailStore(
            data=data,
            mailboxes={
                mid: mailbox_dir(data, url)
                for mid, url in mailboxes.items()
                if mailbox_account(url) in ids and mailbox_name(url) not in EXCLUDED_MAILBOXES
            },
        )
        return Session(
            account=account,
            expires_at=NEVER,
            self_id=frozenset(own),
            label=account.label,
            raw=store,
        )

    def _rows(self, store: MailStore, start_time_ms: int, conversation_id: str | None = None):
        where = message_filter(list(store.mailboxes))
        params: list = [start_time_ms // 1000]
        if conversation_id is not None:
            where += " AND m.conversation_id = ?"
            params.append(int(conversation_id))
        with closing(connect(_index(store.data))) as conn:
            rows = dedup(conn.execute(MESSAGES_SQL.format(where=where), params).fetchall())
            recipients: dict[int, dict[int, list]] = {}
            for r in conn.execute(RECIPIENTS_SQL.format(where=where), params):
                by_type = recipients.setdefault(r["message"], {})
                by_type.setdefault(r["type"], []).append(sender(r["address"], r["comment"]))
        return rows, recipients

    def list_conversations(self, session: Session, start_time_ms: int) -> list[Conversation]:
        rows, recipients = self._rows(session.raw, start_time_ms)
        convs: dict[int, Conversation] = {}
        people: dict[int, set[str]] = {}
        for r in rows:  # mais nova primeiro: o assunto e a data vêm da última mensagem
            cid = r["conversation_id"]
            if cid not in convs:
                convs[cid] = {
                    "id": str(cid),
                    "type": "oneOnOne",
                    "topic": clean_subject(r["subject"]),
                    "createdAt": None,
                    "lastMessageTime": epoch_to_iso(r["date_received"]),
                }
            members = people.setdefault(cid, set())
            for s in [sender(r["address"], r["comment"])] + [
                s for group in recipients.get(r["ROWID"], {}).values() for s in group
            ]:
                if s["mri"]:
                    members.add(s["mri"].lower())
        for cid, conv in convs.items():
            conv["memberCount"] = len(people[cid])
            conv["type"] = "group" if len(people[cid]) > 2 else "oneOnOne"
        return list(convs.values())

    def iter_messages(
        self,
        session: Session,
        conversation: Conversation,
        start_time_ms: int,
        *,
        include_system: bool = False,
        include_raw: bool = False,
    ) -> Iterator[Message]:
        # `include_system` não se aplica: e-mail não tem mensagens de sistema.
        store: MailStore = session.raw
        rows, recipients = self._rows(store, start_time_ms, conversation["id"])
        for r in rows:
            path = emlx_path(store.mailboxes[r["mailbox"]], r["ROWID"])
            # Sem .emlx (o Mail ainda não baixou a mensagem) sai só o envelope.
            text, html = bodies(read_emlx(path)) if path else ("", "")
            to = recipients.get(r["ROWID"], {})
            out: Message = {
                "id": str(r["ROWID"]),
                "conversationId": conversation["id"],
                "conversationTopic": conversation["topic"],
                "composetime": epoch_to_iso(r["date_sent"] or r["date_received"]),
                "from": sender(r["address"], r["comment"]),
                "to": to.get(RECIPIENT_TO, []),
                "cc": to.get(RECIPIENT_CC, []),
                "messagetype": "email",
                "contentHtml": html,
                "contentText": text,
                "isEdited": False,
                "parentMessageId": None,
                "reactions": [],
                "attachments": [],
            }
            if include_raw:
                out["raw"] = {**dict(r), "path": str(path) if path else None}
            yield out


register(MailProvider())
