"""Download das imagens coladas no chat (AMS) para um cache persistente."""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from pathlib import Path

from ...core.models import Attachment

CACHE_DIR = Path.home() / "Library" / "Caches" / "chatmine" / "teams"

# URL -> (bytes, content-type); levanta em qualquer falha.
Fetch = Callable[[str], tuple[bytes, str | None]]


def cache_attachment(att: Attachment, fetch: Fetch, cache_dir: Path = CACHE_DIR) -> Attachment:
    """Baixa um anexo AMS para `cache_dir/<objectId>.<ext>`, reaproveitando o que já está lá.

    Anexos sem `objectId` (SharePoint/OneDrive) voltam intactos; falha no download
    devolve o anexo com `available: false`, sem levantar.
    """
    oid = att.get("objectId")
    if not oid:
        return att
    out = dict(att)
    try:
        hit = next(cache_dir.glob(f"{oid}.*"), None)
        if hit is None:
            data, ctype = fetch(att["url"])
            ext = mimetypes.guess_extension((ctype or "").split(";")[0].strip()) or ".bin"
            hit = cache_dir / f"{oid}{ext}"
            cache_dir.mkdir(parents=True, exist_ok=True)
            # rename atômico; o ponto inicial evita casar com o glob do cache
            tmp = cache_dir / f".{oid}.part"
            tmp.write_bytes(data)
            tmp.replace(hit)
            out["contentType"] = out.get("contentType") or ctype
    except Exception:
        return {**att, "path": None, "available": False}
    return {**out, "path": str(hit), "available": True}
