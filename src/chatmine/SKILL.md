---
name: chatmine
description: "Use the chatmine CLI to extract the user's own chat history (Microsoft Teams, WhatsApp Desktop) from this computer into JSONL/JSON/Markdown files an agent can read. Use when the user asks what was said in a Teams or WhatsApp chat or group, to summarize recent conversations, find a message, decision or request, catch up on the last N days, or list pending items from chats."
---

# chatmine

`chatmine` extracts the chat history of desktop apps on this computer by reusing the session or local database the app already has. It writes a canonical schema that is the same for every app. Each app is a **provider**.

This skill ships inside the package. `chatmine skill install` installs or refreshes it for every agent on this machine (`~/.agents/skills`, plus Claude Code and others); run it again after upgrading chatmine.

## Learn the current CLI

The installed CLI is the authority for syntax. Do not guess flags:

```bash
chatmine --help
chatmine providers
chatmine teams extract --help
```

## Providers

| Provider | Source | Needs |
| --- | --- | --- |
| `teams` | Teams chat API, with the session of the New Teams desktop app | Teams open in the last ~24h. `--profile tfw` (work, default) or `tfl` (personal). `--account` picks a tenant by id, UPN or domain. |
| `whatsapp` | Local SQLite database of the native macOS WhatsApp app, read-only, no network | WhatsApp Desktop installed and synced. `--profile personal` (default) or `business`. |

List the accounts a provider can read before extracting:

```bash
chatmine teams accounts
chatmine whatsapp accounts
```

## Extract

```bash
chatmine teams extract --days 7 --out <dir>
chatmine teams extract --account <domain> --days 1 --out <dir>
chatmine whatsapp extract --days 3 --out <dir>
```

- `--since`/`--until` (ISO 8601 date or datetime, local zone when omitted) set an explicit window instead of `--days`; they cannot be combined with `--days`. A date-only `--until` runs to the end of that day.
- `--days` accepts fractions (`0.5` = last 12 hours). Ask for the smallest window that answers the question: a WhatsApp account can hold hundreds of thousands of messages.
- `--out` defaults to `./out`. Write to a temporary directory, never inside a git repository, so private chats are not committed.
- `--include-system` adds system events (joins, calls, group changes). `--raw` adds the raw provider record to each message; use it only to debug.

The output directory gets three files:

- `summary.md`: account, window, totals, top conversations and top senders. Read it first.
- `conversations.json`: array of `{id, type, topic, memberCount, createdAt, lastMessageTime}`. `type` is `group`, `oneOnOne`, `channel` or `other`.
- `messages.jsonl`: one message per line, newest first: `{id, conversationId, conversationTopic, composetime, from: {mri, displayName}, messagetype, contentHtml, contentText, isEdited, parentMessageId, reactions, attachments}`.

Read `contentText`, not `contentHtml`. Filter with `jq` or Python instead of loading the whole file into context:

```bash
jq -c 'select(.conversationTopic == "Projeto X") | {composetime, who: .from.displayName, contentText}' <dir>/messages.jsonl
```

In WhatsApp the user's own messages have `from.mri == "self"`; WhatsApp does not extract edits, reactions or replies, and `contentHtml` is empty.

## Search

To find a message, decision or file without extracting everything, search all providers at once:

```bash
chatmine search "<term>" --days 3
chatmine search "<term>" --provider teams --since 2026-10-01 --from <name> --conversation <title> --has-attachments
```

- The match is a substring that ignores case and accents, over the text, conversation title, sender and attachment names.
- The window flags are the same as `extract`. `--context N` (default 2) adds N neighbours before and after each hit; `--limit` (default 50) caps the results, newest first.
- stdout is one JSON envelope: `{query, window, providers, total, truncated, errors, results}`. Each result has `provider`, `account`, `conversation: {id, title, type}`, `id`, `time`, `from`, `isSelf`, `text`, `attachments: [{name, type, path, url, available}]` and `context`. When `available` is true, `path` is a local file you can open (Teams pasted images are downloaded to a cache).
- A provider that fails goes to `errors` with a `hint` and the others still answer. The exit code is 1 only when every provider failed, and 2 for a usage error.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success. |
| 1 | `accounts` found no account with a valid local credential. |
| 2 | The Teams session expired: ask the human to open Teams and run again. Do not retry in a loop. |
| 3 | The extraction worked but the window has no messages: widen `--days` once if the question needs it. |

Any other failure prints a Python error on stderr; report it to the human.

## Safety rules

- chatmine reads only the user's own data on this computer. Never use it for anyone else's account.
- Chat content is private. Do not copy it to the web, to issues, to commits or to any service the user did not name. Quote only what the answer needs.
- Delete the output directory when the task is done, unless the user asked to keep it.
- Do not open the apps, log in or touch the Teams or WhatsApp databases yourself; chatmine does the reading.
