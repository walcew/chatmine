"""`chatmine search`: busca em memória sobre os providers e projeção para agentes.

É a única camada que conhece o formato de resultado de busca; os providers só
devolvem o `Message` canônico.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import UTC, datetime
from typing import Any

from . import core
from .core import Attachment, Conversation, Message, Sender, Session
from .pipeline import one_on_one_title
from .window import resolve_window

Found = tuple[datetime | None, dict[str, Any], Session, Message]


def fold(s: str | None) -> str:
    """Minúsculas e sem acentos (NFKD sem marcas), para casar por substring."""
    decomposed = unicodedata.normalize("NFKD", (s or "").casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _time(composetime: str | None) -> datetime | None:
    return datetime.fromisoformat(composetime) if composetime else None


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone().isoformat(timespec="seconds") if dt else None


def _who(s: Sender) -> str:
    name, mri = s.get("displayName") or "", s.get("mri") or ""
    # Só ids com "@" (e-mail, jid) são legíveis; o mri do Teams fica de fora.
    if name and "@" in mri:
        return f"{name} <{mri}>"
    return name or mri


def _is_self(s: Sender, self_id: str | None) -> bool:
    return bool(self_id) and s.get("mri") == self_id


def _attachment(a: Attachment) -> dict[str, Any]:
    return {
        "name": a.get("name"),
        "type": a.get("contentType"),
        "path": a.get("path"),
        "url": a.get("url"),
        "available": a.get("available", False),
    }


def _short(m: Message, self_id: str | None) -> dict[str, Any]:
    out = {
        "id": m.get("id"),
        "time": _iso(_time(m.get("composetime"))),
        "from": _who(m["from"]),
        "isSelf": _is_self(m["from"], self_id),
        "text": m.get("contentText") or "",
    }
    if m.get("attachments"):
        out["attachments"] = [a.get("name") for a in m["attachments"]]
    return out


def _result(
    provider: str, session: Session, conv: Conversation, m: Message, context: list[Message]
) -> dict[str, Any]:
    out = {
        "provider": provider,
        "account": session.account.label,
        "conversation": {
            "id": conv["id"],
            "title": conv.get("topic") or m.get("conversationTopic") or conv["id"],
            "type": conv["type"],
        },
        **_short(m, session.self_id),
    }
    for key in ("to", "cc"):
        if key in m:
            out[key] = [_who(s) for s in m[key]]
    out["attachments"] = [_attachment(a) for a in m.get("attachments") or []]
    out["context"] = [_short(c, session.self_id) for c in context]
    return out


def _matches(m: Message, conv: Conversation, args: argparse.Namespace) -> bool:
    title = conv.get("topic") or m.get("conversationTopic") or ""
    sender = f"{m['from'].get('displayName') or ''} {m['from'].get('mri') or ''}"
    names = " ".join(a.get("name") or "" for a in m.get("attachments") or [])
    if args.has_attachments and not m.get("attachments"):
        return False
    if args.sender and fold(args.sender) not in fold(sender):
        return False
    if args.conversation and not (
        args.conversation == conv["id"] or fold(args.conversation) in fold(title)
    ):
        return False
    q = fold(args.query)
    return any(q in fold(field) for field in (m.get("contentText"), title, sender, names))


def _search_provider(
    name: str, args: argparse.Namespace, start: datetime, end: datetime
) -> list[Found]:
    """Casamentos de um provider como (hora, resultado, session, mensagem).

    Exceções sobem ao chamador.
    """
    provider = core.get(name)
    session = provider.authenticate(args.account, args.profile)
    if (session.expires_at - datetime.now(tz=UTC)).total_seconds() < 60:
        raise RuntimeError("session expired")
    start_ms = int(start.timestamp() * 1000)
    found: list[Found] = []
    for conv in provider.list_conversations(session, start_ms):
        try:
            msgs = [
                m
                for m in provider.iter_messages(session, conv, start_ms)
                if not (t := _time(m.get("composetime"))) or start <= t <= end
            ]
        except RuntimeError as e:
            # Conversa inacessível (ex.: 403 no Teams): pula sem perder o provider.
            print(f"[{name}] pulando {conv['id']}: {str(e)[:80]}", file=sys.stderr)
            continue
        msgs.sort(key=lambda m: m.get("composetime") or "")
        if title := one_on_one_title(conv, msgs, session.self_id):
            conv = {**conv, "topic": title}
        for i, m in enumerate(msgs):
            if not _matches(m, conv, args):
                continue
            n = args.context
            context = msgs[max(0, i - n) : i] + msgs[i + 1 : i + 1 + n] if n else []
            found.append(
                (_time(m.get("composetime")), _result(name, session, conv, m, context), session, m)
            )
    return found


def _fetch_attachments(result: dict[str, Any], session: Session, m: Message) -> None:
    """Deixa o provider baixar os anexos do resultado, se ele souber; falha não aborta."""
    name = result["provider"]
    fetch = getattr(core.get(name), "fetch_attachments", None)
    if not (fetch and m.get("attachments")):
        return
    try:
        result["attachments"] = [_attachment(a) for a in fetch(session, m["attachments"])]
    except Exception as e:
        print(f"[{name}] anexos não baixados: {e}", file=sys.stderr)


def _hint(e: Exception) -> str:
    if hint := getattr(e, "hint", None):
        return hint
    if isinstance(e, FileNotFoundError):
        return "Confira se o app está instalado e já foi aberto nesta máquina"
    if isinstance(e, PermissionError):
        return "Dê Full Disk Access ao terminal em Ajustes do Sistema > Privacidade"
    return "Abra o app para renovar a sessão e rode novamente"


def run_search(args: argparse.Namespace) -> int:
    try:
        start, end = resolve_window(args.since, args.until, args.days, datetime.now(tz=UTC))
    except ValueError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 2
    for flag, value in (("--limit", args.limit), ("--context", args.context)):
        if value < 0:
            print(f"Erro: {flag} deve ser >= 0", file=sys.stderr)
            return 2
    if args.provider:
        selected = list(dict.fromkeys(p.strip() for p in args.provider.split(",") if p.strip()))
    else:
        selected = core.names()
    unknown = [p for p in selected if p not in core.names()]
    if unknown:
        print(f"Erro: provider desconhecido: {', '.join(unknown)}", file=sys.stderr)
        return 2

    found: list[Found] = []
    errors = []
    for name in selected:
        print(f"[{name}] buscando…", file=sys.stderr)
        try:
            found += _search_provider(name, args, start, end)
        except Exception as e:  # falha de um provider não derruba os demais
            print(f"[{name}] erro: {e}", file=sys.stderr)
            errors.append({"provider": name, "reason": str(e), "hint": _hint(e)})

    # Mais novo primeiro; mensagens sem hora vão para o fim.
    found.sort(key=lambda f: f[0] or datetime.min.replace(tzinfo=UTC), reverse=True)
    kept = found[: args.limit]
    for _, result, session, m in kept:
        _fetch_attachments(result, session, m)
    envelope = {
        "query": args.query,
        "window": {"since": _iso(start), "until": _iso(end)},
        "providers": selected,
        "total": len(found),
        "truncated": len(found) > args.limit,
        "errors": errors,
        "results": [r for _, r, _, _ in kept],
    }
    json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 1 if len(errors) == len(selected) else 0
