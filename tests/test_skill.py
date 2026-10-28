import re

import pytest

from chatmine import skill
from chatmine.__main__ import main


@pytest.fixture
def home(tmp_path, monkeypatch):
    # Sem as variáveis que relocariam as pastas dos agentes.
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return tmp_path


def test_skill_has_frontmatter():
    text = skill.skill_text()
    assert text.startswith("---\nname: chatmine\ndescription: ")
    assert "---" in text.splitlines()[1:], "frontmatter não fecha"


def test_skill_prints_itself(capsys):
    assert main(["skill"]) == 0
    assert capsys.readouterr().out == skill.skill_text()


def test_every_cited_command_exists():
    """Todo `chatmine <verbo> [<subverbo>]` citado na skill existe na CLI."""
    cited = set()
    for line in skill.skill_text().splitlines():
        for snippet in [line, *line.split("`")[1::2]]:
            if not snippet.startswith("chatmine "):
                continue
            words = []
            for w in snippet.split()[1:3]:
                if re.match(r"[-<\"]", w):
                    break
                words.append(w)
            if words:
                cited.add(tuple(words))
    assert len(cited) >= 5, cited
    for words in cited:
        with pytest.raises(SystemExit) as exc:
            main([*words, "--help"])
        assert exc.value.code == 0, f"comando citado não existe: {words}"


def test_install_writes_canonical_copy_only(home):
    skill.install(home)
    assert (home / ".agents/skills/chatmine/SKILL.md").read_text() == skill.skill_text()
    assert not (home / ".claude").exists(), "não cria pasta de agente ausente"


def test_install_links_detected_agents(home):
    (home / ".claude").mkdir()
    (home / ".kiro").mkdir()
    agents = [a for a, _ in skill.install(home)]
    canonical = home / ".agents/skills/chatmine"
    for dest in (".claude/skills/chatmine", ".kiro/skills/chatmine"):
        assert (home / dest).is_symlink()
        assert (home / dest).readlink() == canonical
    assert "Claude Code" in agents and "Kiro" in agents
    assert not (home / ".codeium").exists()


def test_install_updates_manual_copy_and_is_idempotent(home):
    old = home / ".claude/skills/chatmine"
    old.mkdir(parents=True)
    (old / "SKILL.md").write_text("versão velha")
    skill.install(home)
    skill.install(home)
    assert (old / "SKILL.md").read_text() == skill.skill_text()


def test_skill_documents_mail_and_search():
    text = skill.skill_text()
    description = text.splitlines()[2]
    assert "Apple Mail" in description and "search" in description
    for topic in ("Full Disk Access", "--include-bulk", "--account", "truncated", "available"):
        assert topic in text, f"skill não cobre {topic}"
    assert "chatmine mail accounts" in text and "chatmine mail extract" in text
