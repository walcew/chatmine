from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from ...core.models import Conversation, Message

MRI_RE = re.compile(r"(?:8:)?(orgid:[0-9a-f-]+|live:[^;]+)", re.I)
# Imagens coladas no chat ficam no AMS; o download (e o host aceito) é do media.py.
AMS_IMAGE = "http://schema.skype.com/AMSImage"


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


def _attachment(name: str | None, content_type: str | None, url: str | None) -> dict[str, Any]:
    return {
        "name": name,
        "contentType": content_type,
        "contentUrl": url,
        "path": None,
        "url": url,
        "available": False,  # o download fica para o search
    }


def _attachments(msg: dict[str, Any], content_html: str) -> list[dict[str, Any]]:
    out = [
        _attachment(a.get("name"), a.get("contentType"), a.get("contentUrl"))
        for a in msg.get("attachments") or []
    ]
    # Arquivos do SharePoint/OneDrive vêm em `properties.files`, uma string JSON.
    try:
        files = json.loads((msg.get("properties") or {}).get("files") or "[]")
    except (TypeError, ValueError):
        files = []
    for f in files if isinstance(files, list) else []:
        if not isinstance(f, dict):
            continue
        info = f.get("fileInfo") or {}
        url = f.get("objectUrl") or info.get("fileUrl") or info.get("shareUrl")
        out.append(_attachment(f.get("fileName") or f.get("title"), None, url))
    if content_html:
        for img in BeautifulSoup(content_html, "html.parser").find_all("img", itemtype=AMS_IMAGE):
            out.append(_attachment(img.get("alt"), None, img.get("src")))
    return out


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
        "attachments": _attachments(msg, content_html),
    }
    if include_raw:
        out["raw"] = msg
    return out
