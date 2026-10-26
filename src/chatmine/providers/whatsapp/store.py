"""Leitura do banco local do WhatsApp Desktop (macOS, app nativo).

O app guarda o histórico em SQLite (Core Data) sem criptografia dentro do group
container. Tudo aqui é leitura read-only: o app continua gravando no banco (WAL)
enquanto está aberto.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...core.models import Conversation, Message

# Core Data grava datas em segundos desde 2001-01-01 UTC.
APPLE_EPOCH = 978307200

CONTAINERS = {
    "personal": "group.net.whatsapp.WhatsApp.shared",
    "business": "group.net.whatsapp.WhatsAppSMB.shared",
}

# ZMESSAGETYPE -> rótulo. Valores observados no schema; desconhecidos viram "type:<n>".
MESSAGE_TYPES = {
    0: "text",
    1: "image",
    2: "video",
    3: "audio",
    4: "contact",
    5: "location",
    6: "system",
    7: "link",
    8: "document",
    10: "system",
    11: "gif",
    14: "deleted",
    15: "sticker",
}
SYSTEM_TYPES = (6, 10)

SELF_ID = "self"  # mensagens próprias não trazem o JID do remetente no banco


def container_root(profile: str | None) -> Path:
    key = profile or "personal"
    if key not in CONTAINERS:
        raise ValueError(f"Perfil {key!r} inválido. Use: {', '.join(CONTAINERS)}")
    return Path.home() / "Library" / "Group Containers" / CONTAINERS[key]


def connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"Banco do WhatsApp não encontrado em {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_names(root: Path) -> dict[str, str]:
    """Mapa JID -> nome: push names do WhatsApp, sobrescritos pela agenda sincronizada."""
    names: dict[str, str] = {}
    with closing(connect(root / "ChatStorage.sqlite")) as conn:
        for r in conn.execute("SELECT ZJID, ZPUSHNAME FROM ZWAPROFILEPUSHNAME"):
            if r["ZJID"] and r["ZPUSHNAME"]:
                names[r["ZJID"]] = r["ZPUSHNAME"]
    contacts = root / "ContactsV2.sqlite"
    if contacts.exists():
        with closing(connect(contacts)) as conn:
            for r in conn.execute(
                "SELECT ZWHATSAPPID, ZLID, ZFULLNAME FROM ZWAADDRESSBOOKCONTACT"
                " WHERE ZFULLNAME IS NOT NULL"
            ):
                for jid in (r["ZWHATSAPPID"], r["ZLID"]):
                    if jid:
                        names[jid] = r["ZFULLNAME"]
    return names


def apple_to_iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts + APPLE_EPOCH, tz=UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ms_to_apple(ms: int) -> float:
    return ms / 1000 - APPLE_EPOCH


def conversation_type(jid: str) -> str:
    if jid.endswith("@g.us"):
        return "group"
    if jid.endswith(("@s.whatsapp.net", "@lid")):
        return "oneOnOne"
    return "other"


CONVERSATIONS_SQL = """
SELECT s.ZCONTACTJID, s.ZPARTNERNAME, s.ZLASTMESSAGEDATE, g.ZCREATIONDATE,
       (SELECT count(*) FROM ZWAGROUPMEMBER gm
         WHERE gm.ZCHATSESSION = s.Z_PK AND gm.ZISACTIVE = 1) AS member_count
FROM ZWACHATSESSION s
LEFT JOIN ZWAGROUPINFO g ON g.Z_PK = s.ZGROUPINFO
WHERE s.ZLASTMESSAGEDATE >= ?
  AND coalesce(s.ZREMOVED, 0) = 0
  AND s.ZCONTACTJID NOT LIKE '%@status' AND s.ZCONTACTJID NOT LIKE '%@broadcast'
ORDER BY s.ZLASTMESSAGEDATE DESC
"""

MESSAGES_SQL = """
SELECT m.Z_PK, m.ZSTANZAID, m.ZMESSAGEDATE, m.ZISFROMME, m.ZFROMJID, m.ZMESSAGETYPE,
       m.ZTEXT, gm.ZMEMBERJID, gm.ZFIRSTNAME,
       mi.ZTITLE AS media_title, mi.ZMEDIALOCALPATH AS media_path
FROM ZWAMESSAGE m
JOIN ZWACHATSESSION s ON s.Z_PK = m.ZCHATSESSION
LEFT JOIN ZWAGROUPMEMBER gm ON gm.Z_PK = m.ZGROUPMEMBER
LEFT JOIN ZWAMEDIAITEM mi ON mi.ZMESSAGE = m.Z_PK
WHERE s.ZCONTACTJID = ? AND m.ZMESSAGEDATE >= ?
ORDER BY m.ZMESSAGEDATE DESC
"""


def normalize_conversation(row: dict[str, Any]) -> Conversation:
    jid = row["ZCONTACTJID"]
    ctype = conversation_type(jid)
    return {
        "id": jid,
        "type": ctype,
        "topic": row.get("ZPARTNERNAME") or "",
        "memberCount": row.get("member_count") if ctype == "group" else 2,
        "createdAt": apple_to_iso(row.get("ZCREATIONDATE")),
        "lastMessageTime": apple_to_iso(row.get("ZLASTMESSAGEDATE")),
    }


def normalize_message(
    row: dict[str, Any],
    conversation: Conversation,
    names: dict[str, str],
    media_root: Path,
    *,
    include_raw: bool = False,
) -> Message:
    if row.get("ZISFROMME"):
        mri, display = SELF_ID, "Eu"
    else:
        # Em grupo o remetente é o membro; em 1:1 é o próprio chat.
        mri = row.get("ZMEMBERJID") or row.get("ZFROMJID")
        display = names.get(mri or "") or row.get("ZFIRSTNAME") or ""
        if not display and conversation["type"] == "oneOnOne":
            display = conversation["topic"]
    mtype = row.get("ZMESSAGETYPE")
    attachments = []
    if row.get("media_path") or row.get("media_title"):
        path = row.get("media_path")
        attachments.append(
            {
                "name": row.get("media_title") or (Path(path).name if path else None),
                "contentType": MESSAGE_TYPES.get(mtype, f"type:{mtype}"),
                "contentUrl": (media_root / path).as_uri() if path else None,
            }
        )
    text = row.get("ZTEXT") or ""
    out: Message = {
        "id": row.get("ZSTANZAID") or str(row.get("Z_PK")),
        "conversationId": conversation["id"],
        "conversationTopic": conversation["topic"],
        "composetime": apple_to_iso(row.get("ZMESSAGEDATE")),
        "from": {"mri": mri, "displayName": display},
        "messagetype": MESSAGE_TYPES.get(mtype, f"type:{mtype}"),
        "contentHtml": "",
        "contentText": text,
        # shortcut: edição, reações e reply ficam em protobuf (ZWAMESSAGEINFO); decodificar
        # quando alguém precisar desses campos.
        "isEdited": False,
        "parentMessageId": None,
        "reactions": [],
        "attachments": attachments,
    }
    if include_raw:
        out["raw"] = dict(row)
    return out
