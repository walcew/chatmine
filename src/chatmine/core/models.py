"""Modelos canônicos, independentes de app.

O schema de SAÍDA (`Conversation`/`Message`) é mantido em camelCase de propósito:
é o contrato que ferramentas de IA já consomem a partir do `messages.jsonl`.
`Account`/`Session` são internos — nunca vão para o disco.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NotRequired, TypedDict


@dataclass(frozen=True)
class Account:
    """Uma identidade logada dentro de um provider (tenant no Teams, workspace no Slack)."""

    id: str
    label: str
    expires_at: datetime  # quando a credencial cacheada desta conta expira
    hint: str | None = None
    raw: Any = field(default=None, repr=False)  # objeto específico do provider


@dataclass(frozen=True)
class Session:
    """Credencial viva de uma Account, obtida reaproveitando a sessão local do app."""

    account: Account
    expires_at: datetime  # quando ESTA sessão morre (checagem de janela curta)
    # id do "eu" no provider, p/ detectar mensagens próprias; no Mail, o conjunto de endereços
    self_id: str | frozenset[str] | None
    label: str  # rótulo humano p/ logs
    raw: Any = field(default=None, repr=False)  # bundle de credenciais do provider


class Sender(TypedDict):
    # `mri` é o id do remetente no provider. O nome vem do Teams (Message Resource
    # Identifier) e é mantido por compatibilidade com consumidores existentes.
    mri: str | None
    displayName: str


class Attachment(TypedDict):
    name: str | None
    contentType: str | None
    contentUrl: str | None
    # Forma única entre providers: `path` é o arquivo local absoluto, `url` o link remoto
    # e `available` diz se o arquivo pode ser aberto agora.
    path: NotRequired[str | None]
    url: NotRequired[str | None]
    available: NotRequired[bool]


class Reaction(TypedDict):
    key: str | None
    count: int


class Conversation(TypedDict):
    id: str
    type: str  # "group" | "oneOnOne" | "channel" | "other"
    topic: str
    memberCount: NotRequired[int | None]
    createdAt: NotRequired[str | None]
    lastMessageTime: NotRequired[str | None]


# `from` é palavra reservada em Python; o schema funcional permite usá-la como chave.
Message = TypedDict(
    "Message",
    {
        "id": str | None,
        "conversationId": str,
        "conversationTopic": str,
        "composetime": str | None,
        "from": Sender,
        "to": NotRequired[list[Sender]],  # destinatários, só em providers que os têm (Mail)
        "cc": NotRequired[list[Sender]],
        "messagetype": str | None,
        "contentHtml": str,
        "contentText": str,
        "isEdited": bool,
        "parentMessageId": str | None,
        "reactions": list[Reaction],
        "attachments": list[Attachment],
        "raw": NotRequired[dict[str, Any]],  # JSON cru do provider, só com --raw
    },
)
