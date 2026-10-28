"""Download das imagens coladas no chat (AMS) para um cache persistente."""

from __future__ import annotations

import mimetypes
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from ...core.models import Attachment


def _cache_root() -> Path:
    if sys.platform == "win32" and (local := os.environ.get("LOCALAPPDATA")):
        return Path(local)
    return Path.home() / "Library" / "Caches"


CACHE_DIR = _cache_root() / "chatmine" / "teams"

# O download leva o skypetoken: só hosts AMS conhecidos, só https.
AMS_HOST_SUFFIXES = (".asm.skype.com", ".asyncgw.teams.microsoft.com")
# O id do objeto nomeia o arquivo no cache.
AMS_OBJECT_RE = re.compile(r"/v1/objects/([^/?]+)/views/")

# URL -> (bytes, content-type); levanta em qualquer falha.
Fetch = Callable[[str], tuple[bytes, str | None]]


def ams_object_id(url: str | None) -> str | None:
    """Id do objeto AMS da URL, ou None se ela não for de um host AMS confiável."""
    parsed = urlparse(url or "")
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host.endswith(AMS_HOST_SUFFIXES):
        return None
    m = AMS_OBJECT_RE.search(parsed.path)
    return m.group(1) if m else None


def cache_attachment(att: Attachment, fetch: Fetch, cache_dir: Path = CACHE_DIR) -> Attachment:
    """Baixa um anexo AMS para `cache_dir/<objectId>.<ext>`, reaproveitando o que já está lá.

    Anexos fora do AMS (SharePoint/OneDrive, hosts desconhecidos) voltam intactos;
    falha no download devolve o anexo com `available: false` e avisa no stderr.
    """
    oid = ams_object_id(att.get("url"))
    if not oid:
        return att
    out = dict(att)
    try:
        hit = next(cache_dir.glob(f"{oid}.*"), None)
        ctype = None
        if hit is None:
            data, ctype = fetch(att["url"])
            ext = mimetypes.guess_extension((ctype or "").split(";")[0].strip()) or ".bin"
            hit = cache_dir / f"{oid}{ext}"
            cache_dir.mkdir(parents=True, exist_ok=True)
            # rename atômico; o ponto inicial evita casar com o glob do cache
            tmp = cache_dir / f".{oid}.part"
            tmp.write_bytes(data)
            tmp.replace(hit)
        out["contentType"] = out.get("contentType") or ctype or mimetypes.guess_type(hit)[0]
    except Exception as e:
        print(f"[teams] anexo não baixado: {str(e)[:120]}", file=sys.stderr)
        return {**att, "path": None, "available": False}
    return {**out, "path": str(hit), "available": True}
