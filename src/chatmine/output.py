from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def write_summary(
    out_dir: Path,
    *,
    provider: str,
    account_label: str,
    window_start: datetime,
    window_end: datetime,
    conversations: list[dict[str, Any]],
    message_counts: dict[str, int],
    sender_counts: Counter[str],
    account_expires: datetime,
    session_expires: datetime,
) -> Path:
    by_id = {c["id"]: c for c in conversations}
    top_convs = sorted(message_counts.items(), key=lambda kv: kv[1], reverse=True)[:20]
    top_senders = sender_counts.most_common(15)

    lines = [
        f"# {provider} — resumo da extração\n",
        f"- Conta: **{account_label}**",
        f"- Janela: **{window_start.isoformat()}** até **{window_end.isoformat()}**",
        f"- Conversas cobertas: **{len(conversations)}**",
        f"- Mensagens totais: **{sum(message_counts.values())}**",
        f"- Credencial da conta expira em: {account_expires.isoformat()}",
        f"- Sessão expira em: {session_expires.isoformat()}",
        "",
        "## Top conversas por volume",
        "",
        "| # | Tipo | Título | Mensagens |",
        "|---|------|--------|-----------|",
    ]
    for i, (cid, n) in enumerate(top_convs, 1):
        c = by_id.get(cid, {})
        topic = (c.get("topic") or "").replace("|", "\\|") or "(sem título)"
        lines.append(f"| {i} | {c.get('type', '?')} | {topic} | {n} |")

    lines += [
        "",
        "## Top remetentes",
        "",
        "| # | Remetente | Mensagens |",
        "|---|-----------|-----------|",
    ]
    for i, (name, n) in enumerate(top_senders, 1):
        name_md = (name or "(desconhecido)").replace("|", "\\|")
        lines.append(f"| {i} | {name_md} | {n} |")

    path = out_dir / "summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
