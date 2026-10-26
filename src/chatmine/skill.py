"""`chatmine skill install`: instala a skill embutida para os agentes de IA desta máquina, com
a mesma lógica do `npx skills add -g`. A cópia canônica fica em `~/.agents/skills`, que os
agentes "universais" (Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode, Cline, Amp) já
leem. Os demais, quando instalados (a pasta deles existe), ganham um link para ela.
"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

NAME = "chatmine"


def skill_text() -> str:
    """A skill empacotada: sempre a da versão instalada da CLI."""
    return files("chatmine").joinpath("SKILL.md").read_text(encoding="utf-8")


def _env_dir(var: str, default: Path) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else default


def linked_agents(home: Path) -> list[tuple[str, Path, Path]]:
    """Agentes que não leem `~/.agents/skills`: nome, pasta que indica que ele está instalado e
    pasta de skills globais dele (a tabela do `npx skills`, só os principais)."""
    claude = _env_dir("CLAUDE_CONFIG_DIR", home / ".claude")
    config = _env_dir("XDG_CONFIG_HOME", home / ".config")
    windsurf = home / ".codeium" / "windsurf"
    return [
        ("Claude Code", claude, claude / "skills"),
        ("Windsurf", windsurf, windsurf / "skills"),
        ("Goose", config / "goose", config / "goose" / "skills"),
        ("Kiro", home / ".kiro", home / ".kiro" / "skills"),
    ]


def install(home: Path | None = None) -> list[tuple[str, Path]]:
    """Grava a cópia canônica e liga os agentes detectados. Devolve (agente, destino)."""
    home = home or Path.home()
    text = skill_text()
    canonical = home / ".agents" / "skills" / NAME
    canonical.mkdir(parents=True, exist_ok=True)
    (canonical / "SKILL.md").write_text(text, encoding="utf-8")
    done = [("Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode e outros", canonical)]
    for agent, installed, skills in linked_agents(home):
        if not installed.is_dir():
            continue
        dest = skills / NAME
        _link_or_copy(canonical, dest, text)
        done.append((agent, dest))
    return done


def _link_or_copy(canonical: Path, dest: Path, text: str) -> None:
    """Liga `dest` à cópia canônica, como o `npx skills`. Uma pasta de verdade já no lugar (a
    instalação manual antiga) é atualizada por cópia, e o link que falha (Windows sem
    privilégio de symlink) também vira cópia."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink():
        dest.unlink()
    if not dest.exists():
        try:
            dest.symlink_to(canonical, target_is_directory=True)
            return
        except OSError:
            pass
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(text, encoding="utf-8")
