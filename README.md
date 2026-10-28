# chatmine

CLI que extrai o histórico de chats de apps desktop **reaproveitando a sessão local
já autenticada** — sem abrir fluxo OAuth nem depender de consentimento corporativo de
app. A saída é um schema canônico (`messages.jsonl` + `conversations.json` + um
`summary.md`) pensado para ser consumido por ferramentas de IA, sem precisar de um
conector MCP.

> **Só os seus próprios dados.** O `chatmine` lê apenas o que a sua conta, na sua
> máquina, já tem acesso, reutilizando a sessão que o app já abriu para você. Não
> contorna autenticação, não acessa dados de terceiros e não deve ser usado para isso.

## Como funciona

1. Descobre a chave mestra de criptografia de cookies do SO (Keychain no macOS, DPAPI
   no Windows).
2. Lê e decripta os cookies de sessão do cofre Chromium embutido no app.
3. Chama a API nativa do app com a sessão viva, lista as conversas e pagina as mensagens.
4. Normaliza tudo para o schema canônico e grava em `--out`.

A camada de decriptação é genérica (um `ChromiumVault` por app); cada app é um
**provider**. Hoje: `teams` (via API) e `whatsapp` (100% local, lê o SQLite do app). Adicionar Slack/Discord é declarar o cofre deles + o
cliente de API + a normalização — nenhuma cripta nova.

## Instalação

```bash
brew install walcew/tap/chatmine
chatmine skill install    # opcional: ensina a CLI aos agentes de IA desta máquina
```

A partir do código-fonte:

```bash
pipx install .
# ou, para desenvolvimento:
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

## Uso

```bash
chatmine providers                         # lista os providers registrados
chatmine teams accounts                    # contas (tenants) com sessão local válida
chatmine teams accounts --profile tfl      # perfil pessoal (default: tfw = work)
chatmine teams extract --account contoso.com --days 7 --out ./out
chatmine teams extract --days 7 --raw      # inclui o JSON cru de cada mensagem
chatmine whatsapp extract --days 7 --out ./out
chatmine whatsapp extract --profile business --days 7   # WhatsApp Business
chatmine teams extract --since 2026-10-01 --until 2026-10-02   # janela fixa (fuso local; --until só data vai até 23:59:59)
```

`--account` aceita tenant-id (ou prefixo), UPN ou domínio. Sem ele, usa a conta com a
credencial emitida mais recentemente.

### Pré-requisitos (Teams)

New Teams (`com.microsoft.teams2` no macOS / MSIX `MSTeams_*` no Windows) instalado e
logado em ≥ 1 conta work/school, aberto recentemente (a sessão vive ~24h; reabra o app
para renovar). Python 3.11+.

No Windows, rode sob o **mesmo usuário** logado no Teams. Perfis com app-bound
encryption (v20) exigem privilégios SYSTEM — o CLI detecta e explica.

### Pré-requisitos (WhatsApp)

WhatsApp Desktop nativo do macOS (`/Applications/WhatsApp.app`) instalado e sincronizado.
O provider lê, em modo read-only, o `ChatStorage.sqlite` do group container
(`~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared`) e resolve nomes pela
agenda sincronizada (`ContactsV2.sqlite`). Não há API, token nem expiração de sessão.
Mensagens próprias saem com `from.mri = "self"`. Edição, reações e reply não são
extraídos (ficam em protobuf). Anexos apontam para o arquivo local, quando baixado.

## Skill para agentes de IA

A CLI traz embutida uma skill (em inglês) que ensina agentes de IA a usá-la:

```bash
chatmine skill            # imprime a skill
chatmine skill install    # instala para os agentes desta máquina
```

O `install` segue a lógica do `npx skills add -g`. A cópia canônica vai para
`~/.agents/skills/chatmine`, que já é lida por Codex, Cursor, Gemini CLI, GitHub Copilot,
OpenCode e outros. Claude Code, Windsurf, Goose e Kiro, quando instalados, ganham um
link para ela. Rode de novo depois de atualizar o chatmine.

## Teste manual (smoke test)

O caminho de extração ao vivo exige uma sessão autenticada real, então não roda em CI.
Para validar ponta a ponta:

```bash
chatmine teams accounts        # deve listar ao menos uma conta
chatmine teams extract --days 1 --out /tmp/chatmine-smoke
cat /tmp/chatmine-smoke/summary.md
```

Os testes automatizados (`pytest`) cobrem só as partes determinísticas: normalização,
montagem de query e o registry.

## Licença

MIT.
