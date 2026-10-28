"""Leitura do Apple Mail local (macOS).

O índice das mensagens fica no SQLite `MailData/Envelope Index` do diretório de
dados atual (`V10` hoje) e o corpo de cada mensagem num `.emlx` (RFC 822 com o
tamanho na primeira linha e um plist no fim). Tudo é read-only: o Mail continua
gravando no banco (WAL) enquanto está aberto. O schema não é documentado e muda
entre versões do macOS, por isso as consultas ficam todas aqui.
"""

from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from bs4 import BeautifulSoup

from ..teams.normalize import html_to_text

# Aponta para o equivalente a ~/Library/Mail; o Accounts4.sqlite é lido de ../Accounts.
ROOT_ENV = "CHATMINE_MAIL_ROOT"

FDA_HINT = (
    "Sem acesso aos dados do Apple Mail. Dê Full Disk Access ao terminal em Ajustes do "
    "Sistema > Privacidade e Segurança > Acesso Total ao Disco e abra o terminal de novo."
)

# Nome da pasta (último segmento, NFC, casefold) -> pasta ignorada / pasta de enviados.
EXCLUDED_MAILBOXES = {
    "lixeira", "trash", "deleted items", "deleted messages", "itens excluídos",
    "spam", "junk", "junk e-mail", "junk email", "lixo eletrônico",
}
SENT_MAILBOXES = {
    "sent", "sent items", "sent messages", "sent mail", "enviados", "itens enviados",
    "e-mails enviados", "mensagens enviadas",
}

SUBJECT_PREFIX_RE = re.compile(r"^(?:\s*(?:re|res|fw|fwd|enc)\s*:)+\s*", re.I)

RECIPIENT_TO, RECIPIENT_CC = 0, 1

# Início do histórico citado: "Em ... escreveu:" / "On ... wrote:" (pode quebrar linha), a linha
# "Nome <email> escreveu:" sem o "Em" ou o bloco "De:/From: ... Enviado:/Sent:" do Outlook.
# Marcadores só em PT e EN.
QUOTE_START_RE = re.compile(
    r"^(?:(?:(?:Em|On) .{0,300}?|[^\n]{0,300}?)(?:escreveu|wrote):[ \t]*$"
    r"|(?:De|From):(?:[^\n]*\n){0,3}?[^\n]*?\b(?:Enviado|Sent):)",
    re.M | re.S,
)


def mail_root() -> Path:
    return Path(os.environ.get(ROOT_ENV) or Path.home() / "Library" / "Mail")


def data_dir() -> Path:
    """Diretório de dados mais novo (`V<n>`) que tem o Envelope Index."""
    root = mail_root()
    try:
        versions = [
            p for p in root.iterdir()
            if re.fullmatch(r"V\d+", p.name) and (p / "MailData" / "Envelope Index").exists()
        ]
    except PermissionError:
        raise PermissionError(FDA_HINT) from None
    except FileNotFoundError:
        raise FileNotFoundError(f"Apple Mail não encontrado em {root}") from None
    if not versions:
        raise FileNotFoundError(f"Envelope Index do Apple Mail não encontrado em {root}")
    return max(versions, key=lambda p: int(p.name[1:]))


def connect(path: Path) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
    except sqlite3.OperationalError:
        raise PermissionError(f"{FDA_HINT} ({path})") from None
    conn.row_factory = sqlite3.Row
    return conn


def mailbox_account(url: str) -> str:
    # ews://<UUID>/Caixa%20de%20Entrada, imap://<UUID>/%5BGmail%5D/Spam, local://<UUID>/...
    return url.split("/")[2]


def mailbox_segments(url: str) -> list[str]:
    return [unquote(s) for s in url.split("/")[3:] if s]


def mailbox_name(url: str) -> str:
    segments = mailbox_segments(url)
    return unicodedata.normalize("NFC", segments[-1]).casefold() if segments else ""


def mailbox_dir(data: Path, url: str) -> Path:
    return data.joinpath(mailbox_account(url), *(f"{s}.mbox" for s in mailbox_segments(url)))


def emlx_path(mbox: Path, rowid: int) -> Path | None:
    """`.emlx` da mensagem: os dígitos de ROWID // 1000 invertidos viram subpastas."""
    quotient = rowid // 1000
    digits = list(reversed(str(quotient))) if quotient else []
    try:
        stores = [p for p in mbox.iterdir() if p.is_dir()]
    except FileNotFoundError:
        return None
    for store in stores:
        messages = store.joinpath("Data", *digits, "Messages")
        for name in (f"{rowid}.emlx", f"{rowid}.partial.emlx"):
            if (messages / name).exists():
                return messages / name
    return None


def read_emlx(path: Path) -> EmailMessage:
    data = path.read_bytes()
    size, _, rest = data.partition(b"\n")
    return BytesParser(policy=policy.default).parsebytes(rest[: int(size)])


def _part_text(part: Any) -> str:
    try:
        return part.get_content()
    except Exception:  # charset desconhecido ou MIME quebrado: melhor texto parcial que nada
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", "replace")


def strip_quoted(text: str) -> str:
    """Só o texto novo: corta do marcador de citação em diante e tira as linhas com `>`."""
    text = text.replace("\r\n", "\n")
    if m := QUOTE_START_RE.search(text):
        text = text[: m.start()]
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith(">")).strip()


def _html_without_quotes(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for quote in soup.find_all("blockquote"):
        quote.decompose()
    return str(soup)


def bodies(msg: EmailMessage) -> tuple[str, str]:
    """(texto sem citações, html completo). O texto vem do text/plain ou, na falta dele, do HTML.

    Se o corte esvaziar o texto, vale o corpo inteiro.
    """
    plain = msg.get_body(("plain",))
    html_part = msg.get_body(("html",))
    html = _part_text(html_part) if html_part else ""
    if plain:
        full = _part_text(plain).strip()
        return strip_quoted(full) or full, html
    return strip_quoted(html_to_text(_html_without_quotes(html))) or html_to_text(html), html


def clean_subject(subject: str | None) -> str:
    return SUBJECT_PREFIX_RE.sub("", subject or "").strip()


def epoch_to_iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts, tz=UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sender(address: str | None, comment: str | None) -> dict[str, Any]:
    return {"mri": address, "displayName": comment or address or ""}


def account_labels(data: Path) -> dict[str, str]:
    """UUID da conta -> primeiro e-mail achado na conta ou na conta-mãe (Gmail vem sem)."""
    db = mail_root().parent / "Accounts" / "Accounts4.sqlite"
    if not db.exists():
        return {}
    labels: dict[str, str] = {}
    with closing(connect(db)) as conn:
        rows = conn.execute(
            "SELECT a.ZIDENTIFIER, a.ZACCOUNTDESCRIPTION, a.ZUSERNAME, p.ZUSERNAME,"
            " p.ZACCOUNTDESCRIPTION FROM ZACCOUNT a"
            " LEFT JOIN ZACCOUNT p ON p.Z_PK = a.ZPARENTACCOUNT"
        ).fetchall()
    for ident, *candidates in rows:
        email = next((c for c in candidates if c and "@" in c), None)
        if ident and email:
            labels[ident] = email
    return labels


def sent_senders(conn: sqlite3.Connection, mailboxes: dict[int, str]) -> dict[str, list[str]]:
    """UUID da conta -> remetentes das pastas de enviados, do mais frequente ao menos."""
    sent = [mid for mid, url in mailboxes.items() if mailbox_name(url) in SENT_MAILBOXES]
    if not sent:
        return {}
    rows = conn.execute(
        "SELECT m.mailbox, a.address, count(*) AS n FROM messages m"
        " JOIN addresses a ON a.ROWID = m.sender"
        f" WHERE m.mailbox IN ({','.join('?' * len(sent))})"
        " GROUP BY m.mailbox, a.address ORDER BY n DESC",
        sent,
    ).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(mailbox_account(mailboxes[r["mailbox"]]), []).append(r["address"].lower())
    return out


def load_mailboxes(conn: sqlite3.Connection) -> dict[int, str]:
    return {r["ROWID"]: r["url"] for r in conn.execute("SELECT ROWID, url FROM mailboxes")}


def message_filter(mailbox_ids: list[int]) -> str:
    return (
        "m.deleted = 0 AND m.date_received >= ?"
        f" AND m.mailbox IN ({','.join(str(int(i)) for i in mailbox_ids)})"
    )


MESSAGES_SQL = """
SELECT m.ROWID, m.message_id, m.global_message_id, m.conversation_id, m.mailbox,
       m.date_sent, m.date_received, s.subject, a.address, a.comment
FROM messages m
JOIN subjects s ON s.ROWID = m.subject
LEFT JOIN addresses a ON a.ROWID = m.sender
WHERE {where}
ORDER BY m.date_received DESC, m.ROWID
"""

RECIPIENTS_SQL = """
SELECT r.message, r.type, a.address, a.comment
FROM recipients r JOIN addresses a ON a.ROWID = r.address
WHERE r.message IN (SELECT m.ROWID FROM messages m WHERE {where})
ORDER BY r.message, r.type, r.position
"""


def dedup(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """A mesma mensagem em várias pastas aparece uma vez (a primeira na ordem da consulta)."""
    seen: set[tuple[str, int]] = set()
    out = []
    for r in rows:
        key = ("m", r["message_id"]) if r["message_id"] else ("g", r["global_message_id"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out
