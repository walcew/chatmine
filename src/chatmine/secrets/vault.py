from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChromiumVault:
    """Descreve ONDE e COMO ler o cookie store local de um app baseado em Chromium.

    A decriptação (Keychain/DPAPI + AES v10/v20) é compartilhada e não conhece
    app nenhum; cada provider só fornece estes dados.
    """

    keychain_service: str  # nome do serviço no Keychain do macOS
    cookie_names: tuple[str, ...]  # whitelist de nomes de cookie a ler
    host_filters: tuple[str, ...]  # padrões SQL LIKE para host_key (já com %)
    cookie_dbs: Callable[[str | None], list[Path]]  # (profile) -> SQLite candidatos
    local_state: Callable[[], Path]  # fonte da master key no Windows
