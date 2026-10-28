from __future__ import annotations

import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from . import core
from .core import Conversation, Message
from .output import write_json, write_jsonl, write_summary
from .window import resolve_window

console = Console()


def one_on_one_title(conv: Conversation, msgs: list[Message], self_id: str | None) -> str | None:
    """Chat 1:1 sem título: nome do primeiro interlocutor que não é o usuário."""
    if conv["type"] != "oneOnOne" or conv["topic"]:
        return None
    return next(
        (
            m["from"]["displayName"]
            for m in msgs
            if m["from"]["mri"] and m["from"]["mri"] != self_id and m["from"]["displayName"]
        ),
        None,
    )


def _after(composetime: str | None, limit: datetime) -> bool:
    return bool(composetime) and datetime.fromisoformat(composetime) > limit


def run_extract(
    provider_name: str,
    *,
    selector: str | None,
    profile: str | None,
    days: float | None,
    since: str | None = None,
    until: str | None = None,
    out_dir: str,
    include_system: bool,
    include_raw: bool,
) -> int:
    provider = core.get(provider_name)
    now = datetime.now(tz=UTC)
    try:
        window_start, window_end = resolve_window(since, until, days, now)
    except ValueError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 2
    session = provider.authenticate(selector, profile)

    ttl = session.expires_at - now
    if ttl.total_seconds() < 60:
        console.print(
            "[red]A sessão local já expirou ou expira em <1min.[/] "
            "Abra o app para renovar a sessão e rode novamente."
        )
        return 2
    console.print(f"[green]Sessão ok[/] — {session.label} (expira em {ttl})")

    start_ms = int(window_start.timestamp() * 1000)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    console.print(f"Listando conversas desde {window_start.isoformat()}…")
    conversations = provider.list_conversations(session, start_ms)
    console.print(f"  {len(conversations)} conversas")

    self_id = session.self_id
    all_messages: list[dict] = []
    msg_counts: dict[str, int] = {}
    sender_counts: Counter[str] = Counter()

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as prog:
        task = prog.add_task("Baixando mensagens", total=len(conversations))
        for conv in conversations:
            cid = conv["id"]
            topic = conv.get("topic") or cid
            prog.update(task, description=f"  {topic[:40]}")
            count = 0
            conv_msgs: list[Message] = []
            try:
                for norm in provider.iter_messages(
                    session,
                    conv,
                    start_ms,
                    include_system=include_system,
                    include_raw=include_raw,
                ):
                    # O provider só recebe o início; o corte por `until` é aqui.
                    if until and _after(norm.get("composetime"), window_end):
                        continue
                    norm["conversationId"] = cid
                    all_messages.append(norm)
                    count += 1
                    sender = norm["from"]["displayName"] or norm["from"]["mri"] or "?"
                    sender_counts[sender] += 1
                    conv_msgs.append(norm)
            except RuntimeError as e:
                # Conversa inacessível (ex.: 403 em reunião da qual não somos
                # membros do roster) — pula sem abortar a extração.
                console.print(f"  [yellow]pulando {topic[:40]}: {str(e)[:80]}[/yellow]")
            if name := one_on_one_title(conv, conv_msgs, self_id):
                conv["topic"] = name
                for m in conv_msgs:
                    if not m["conversationTopic"]:
                        m["conversationTopic"] = name
            msg_counts[cid] = count
            prog.advance(task)

    all_messages.sort(key=lambda m: (m.get("composetime") or ""), reverse=True)
    write_jsonl(out / "messages.jsonl", all_messages)
    write_json(out / "conversations.json", conversations)
    summary_path = write_summary(
        out,
        provider=provider_name,
        account_label=session.account.label,
        window_start=window_start,
        window_end=window_end,
        conversations=conversations,
        message_counts=msg_counts,
        sender_counts=sender_counts,
        account_expires=session.account.expires_at,
        session_expires=session.expires_at,
    )

    console.print(
        f"[bold green]OK[/] — {sum(msg_counts.values())} mensagens em "
        f"{len(conversations)} conversas. Veja {summary_path}"
    )
    if not all_messages:
        console.print(
            "[yellow]Nenhuma mensagem — janela sem atividade ou filtros muito restritivos.[/]"
        )
        return 3
    return 0
