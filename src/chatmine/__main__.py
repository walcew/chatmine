from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from . import __version__, core, providers  # noqa: F401  providers registra os providers


def _cmd_providers(args: argparse.Namespace) -> int:
    for name in core.names():
        print(name)
    return 0


def _cmd_skill(args: argparse.Namespace) -> int:
    from . import skill

    if args.action != "install":
        sys.stdout.write(skill.skill_text())
        return 0
    for agent, dest in skill.install():
        print(f"{dest}  ({agent})")
    print("Rode de novo depois de atualizar o chatmine, para a skill acompanhar a CLI.")
    return 0


def _cmd_accounts(args: argparse.Namespace) -> int:
    provider = core.get(args.provider)
    accounts = provider.discover_accounts(args.profile)
    if not accounts:
        print("Nenhuma conta com credencial local válida.", file=sys.stderr)
        return 1
    now = datetime.now(tz=UTC)
    for a in sorted(accounts, key=lambda x: x.label):
        ttl = a.expires_at - now
        hint = f" hint={a.hint}" if a.hint else ""
        print(f"- {a.label}  id={a.id}{hint}  expira_em={ttl}")
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    from .pipeline import run_extract

    return run_extract(
        args.provider,
        selector=args.account,
        profile=args.profile,
        days=args.days,
        out_dir=args.out,
        include_system=args.include_system,
        include_raw=args.raw,
    )


def _add_provider_commands(sub: argparse._SubParsersAction, name: str) -> None:
    pp = sub.add_parser(name, help=f"Opera no provider {name}")
    psub = pp.add_subparsers(dest="verb", required=True)

    pa = psub.add_parser("accounts", help="Lista contas disponíveis na sessão local")
    pa.add_argument("--profile", default=None, help="Perfil/instalação (ex. Teams: tfw|tfl)")
    pa.set_defaults(func=_cmd_accounts, provider=name)

    pe = psub.add_parser("extract", help="Extrai mensagens dos últimos N dias")
    pe.add_argument("--account", default=None, help="Seletor da conta (tenant-id, UPN ou domínio)")
    pe.add_argument("--profile", default=None, help="Perfil/instalação (ex. Teams: tfw|tfl)")
    pe.add_argument("--days", type=float, default=7.0)
    pe.add_argument("--out", default="./out")
    pe.add_argument("--include-system", action="store_true", help="Inclui mensagens de sistema")
    pe.add_argument("--raw", action="store_true", help="Inclui o JSON cru de cada mensagem")
    pe.set_defaults(func=_cmd_extract, provider=name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chatmine",
        description="Extrai histórico de chats reaproveitando a sessão local autenticada.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prov = sub.add_parser("providers", help="Lista os providers registrados")
    p_prov.set_defaults(func=_cmd_providers)

    p_skill = sub.add_parser(
        "skill",
        help="Imprime as instruções de uso da CLI para agentes de IA (em inglês). "
        "`skill install` as instala para os agentes desta máquina.",
    )
    p_skill.add_argument(
        "action",
        nargs="?",
        choices=["install"],
        help="install: grava em ~/.agents/skills (Codex, Cursor, Gemini CLI, Copilot, OpenCode…) "
        "e liga aos agentes que leem outra pasta (Claude Code, Windsurf, Goose, Kiro)",
    )
    p_skill.set_defaults(func=_cmd_skill)

    for name in core.names():
        _add_provider_commands(sub, name)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
