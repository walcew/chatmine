from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from .models import Account, Conversation, Message, Session


@runtime_checkable
class Provider(Protocol):
    """Adaptador de um app de chat.

    Cada provider é dono do seu cliente de API e da sua normalização
    (raw -> canônico). O core nunca vê o formato cru de app nenhum.
    `profile` é um seletor opcional de perfil/instalação que o provider
    interpreta como quiser (no Teams: "tfw"/"tfl"); providers que não têm
    perfis ignoram.
    """

    name: str

    def discover_accounts(self, profile: str | None = None) -> list[Account]:
        """Contas com credencial local válida, sem autenticar em nada novo."""
        ...

    def authenticate(self, selector: str | None = None, profile: str | None = None) -> Session:
        """Resolve o seletor numa Account e devolve a Session viva dela."""
        ...

    def list_conversations(self, session: Session, start_time_ms: int) -> list[Conversation]:
        """Conversas com atividade a partir de `start_time_ms` (epoch ms)."""
        ...

    def iter_messages(
        self,
        session: Session,
        conversation: Conversation,
        start_time_ms: int,
        *,
        include_system: bool = False,
        include_raw: bool = False,
    ) -> Iterator[Message]:
        """Mensagens da conversa, da mais nova para a mais antiga, até a janela."""
        ...
