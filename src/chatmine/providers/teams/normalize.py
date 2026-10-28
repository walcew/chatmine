from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from ...core.models import Conversation, Message

MRI_RE = re.compile(r"(?:8:)?(orgid:[0-9a-f-]+|live:[^;]+)", re.I)


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for at in soup.find_all("at"):
        label = at.get_text(strip=True)
        at.replace_with(f"@{label}" if label else "@")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text()
    # colapsa espaços em cada linha, preservando quebras
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def parse_from(raw: str | None) -> str | None:
    """Extrai o mri skype (ex.: '8:orgid:<uuid>') da URL/valor do campo `from`."""
    if not raw:
        return None
    m = MRI_RE.search(raw)
    if not m:
        return None
    mri = m.group(1)
    return f"8:{mri}" if not mri.startswith("8:") else mri


def normalize_conversation(conv: dict[str, Any]) -> Conversation:
    cid = conv.get("id", "")
    tp = conv.get("threadProperties") or {}
    props = conv.get("properties") or {}
    if cid.endswith("@thread.v2"):
        ctype = "group"
    elif cid.endswith("@unq.gbl.spaces"):
        ctype = "oneOnOne"
    elif cid.endswith("@thread.tacv2"):
        ctype = "channel"
    else:
        ctype = "other"
    return {
        "id": cid,
        "type": ctype,
        "topic": tp.get("topic") or "",
        "memberCount": tp.get("memberCount") or tp.get("membercount"),
        "createdAt": tp.get("createdat") or props.get("createdat"),
        "lastMessageTime": (conv.get("lastMessage") or {}).get("composetime"),
    }


def normalize_message(
    msg: dict[str, Any],
    conv_topic: str,
    *,
    include_raw: bool = False,
) -> Message:
    content_html = msg.get("content") or ""
    from_mri = parse_from(msg.get("from"))
    props = msg.get("properties") or {}
    reactions = [
        {"key": r.get("key"), "count": len(r.get("users") or [])}
        for r in (props.get("emotions") or [])
    ]
    out: Message = {
        "id": msg.get("id"),
        "conversationId": msg.get("conversationLink", "").rsplit("/", 1)[-1]
        or msg.get("threadtopic")
        or "",
        "conversationTopic": conv_topic,
        "composetime": msg.get("composetime"),
        "from": {
            "mri": from_mri,
            "displayName": msg.get("imdisplayname") or "",
        },
        "messagetype": msg.get("messagetype"),
        "contentHtml": content_html,
        "contentText": html_to_text(content_html),
        "isEdited": bool(props.get("edittime")),
        "parentMessageId": props.get("parentmessageid"),
        "reactions": reactions,
        "attachments": [
            {
                "name": a.get("name"),
                "contentType": a.get("contentType"),
                "contentUrl": a.get("contentUrl"),
                "path": None,
                "url": a.get("contentUrl"),
                "available": False,  # o Teams só tem o link remoto; não há arquivo local
            }
            for a in (msg.get("attachments") or [])
        ],
    }
    if include_raw:
        out["raw"] = msg
    return out
