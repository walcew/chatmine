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
        since=args.since,
        until=args.until,
        out_dir=args.out,
        include_system=args.include_system,
        include_raw=args.raw,
        include_bulk=args.include_bulk,
    )


def _cmd_search(args: argparse.Namespace) -> int:
    from .search import run_search

    return run_search(args)


def _add_search_command(sub: argparse._SubParsersAction) -> None:
    ps = sub.add_parser(
        "search", help="Busca um termo em todos os providers e imprime um JSON no stdout"
    )
    ps.add_argument("query", help="Termo; ignora maiúsculas e acentos")
    ps.add_argument("--provider", default=None, help="Lista separada por vírgula (padrão: todos)")
    ps.add_argument("--account", default=None, help="Seletor da conta, repassado aos providers")
    ps.add_argument("--profile", default=None, help="Perfil/instalação, repassado aos providers")
    ps.add_argument("--days", type=float, default=None, help="Últimos N dias (padrão 7)")
    ps.add_argument("--since", default=None, help="Início, ISO 8601 (fuso local se omitido)")
    ps.add_argument("--until", default=None, help="Fim da janela; só data vale até o fim do dia")
    ps.add_argument("--from", dest="sender", default=None, help="Filtra pelo remetente")
    ps.add_argument("--conversation", default=None, help="Filtra pela conversa (id ou título)")
    ps.add_argument("--has-attachments", action="store_true", help="Só mensagens com anexo")
    ps.add_argument("--context", type=int, default=2, help="Vizinhas antes e depois (0 desliga)")
    ps.add_argument(
        "--include-bulk", action="store_true", help="Inclui newsletters e envios em massa (Mail)"
    )
    ps.add_argument("--limit", type=int, default=50, help="Máximo de resultados (padrão 50)")
    ps.set_defaults(func=_cmd_search)


def _add_provider_commands(sub: argparse._SubParsersAction, name: str) -> None:
    pp = sub.add_parser(name, help=f"Opera no provider {name}")
    psub = pp.add_subparsers(dest="verb", required=True)

    pa = psub.add_parser("accounts", help="Lista contas disponíveis na sessão local")
    pa.add_argument("--profile", default=None, help="Perfil/instalação (ex. Teams: tfw|tfl)")
    pa.set_defaults(func=_cmd_accounts, provider=name)

    pe = psub.add_parser("extract", help="Extrai mensagens dos últimos N dias ou de uma janela")
    pe.add_argument(
        "--account", default=None, help="Seletor da conta (tenant-id, UPN, domínio ou e-mail)"
    )
    pe.add_argument("--profile", default=None, help="Perfil/instalação (ex. Teams: tfw|tfl)")
    pe.add_argument("--days", type=float, default=None, help="Últimos N dias (padrão 7)")
    pe.add_argument("--since", default=None, help="Início, ISO 8601 (fuso local se omitido)")
    pe.add_argument("--until", default=None, help="Fim da janela; só data vale até o fim do dia")
    pe.add_argument("--out", default="./out")
    pe.add_argument("--include-system", action="store_true", help="Inclui mensagens de sistema")
    pe.add_argument(
        "--include-bulk", action="store_true", help="Inclui newsletters e envios em massa (Mail)"
    )
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

    _add_search_command(sub)

    for name in core.names():
        _add_provider_commands(sub, name)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (PermissionError, FileNotFoundError, ValueError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
