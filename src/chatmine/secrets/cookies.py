from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .vault import ChromiumVault


@dataclass(frozen=True)
class CookieRow:
    host: str
    name: str
    value: str
    path: str = ""
    last_access_utc: int = 0


def build_query(vault: ChromiumVault) -> tuple[str, list[str]]:
    """Monta o SELECT e os parâmetros para os filtros do vault. Função pura (testável)."""
    host_clause = " OR ".join(["host_key LIKE ?"] * len(vault.host_filters))
    name_clause = ",".join(["?"] * len(vault.cookie_names))
    sql = (
        "SELECT host_key, name, path, encrypted_value, last_access_utc "
        "FROM cookies "
        f"WHERE ({host_clause}) AND name IN ({name_clause}) "
        "ORDER BY last_access_utc DESC"
    )
    params = list(vault.host_filters) + list(vault.cookie_names)
    return sql, params


def _maybe_strip_host_prefix(plaintext: bytes) -> bytes:
    """Alguns builds do Chromium prefixam SHA-256(host) (32 bytes) ao plaintext.

    Heurística: se o início é não-ASCII e o fim começa com ASCII imprimível, corta.
    """
    if len(plaintext) < 33:
        return plaintext
    head, tail = plaintext[:32], plaintext[32:]
    head_printable = all(32 <= b < 127 for b in head)
    tail_printable = all(32 <= b < 127 for b in tail[:16])
    if not head_printable and tail_printable:
        return tail
    return plaintext


def read_cookies(vault: ChromiumVault, profile: str | None = None) -> list[CookieRow]:
    # Import tardio: _backend decide o impl por plataforma só quando chamado.
    from ._backend import BackendError, decrypt_cookie, get_master_key

    key = get_master_key(vault)
    sql, params = build_query(vault)
    rows: list[CookieRow] = []
    for db_path in vault.cookie_dbs(profile):
        uri = f"file:{db_path}?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as conn:
            for host, name, path, ev, lau in conn.execute(sql, params):
                try:
                    pt = decrypt_cookie(ev, key)
                except BackendError:
                    continue
                pt = _maybe_strip_host_prefix(pt)
                try:
                    value = pt.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                rows.append(
                    CookieRow(
                        host=host,
                        name=name,
                        value=value,
                        path=path or "",
                        last_access_utc=lau or 0,
                    )
                )
    return rows
