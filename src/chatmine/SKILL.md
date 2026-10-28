---
name: chatmine
description: "Use the chatmine CLI to extract the user's own chat history (Microsoft Teams, WhatsApp Desktop) and email (Apple Mail) from this computer into JSONL/JSON/Markdown files an agent can read, and to search them. Use when the user asks what was said in a Teams or WhatsApp chat or group, what an email said, to find a message, decision, request or attachment (`chatmine search`), to summarize recent conversations, catch up on the last N days, or list pending items from chats and email."
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
| `mail` | Apple Mail index and `.emlx` files in `~/Library/Mail`, read-only, no network | Apple Mail set up on this Mac, and **Full Disk Access** for the terminal or agent app (System Settings > Privacy & Security). `--account` picks one account by id, address or domain; without it every account is read. |

List the accounts a provider can read before extracting:

```bash
chatmine teams accounts
chatmine whatsapp accounts
chatmine mail accounts
```

## Extract

```bash
chatmine teams extract --days 7 --out <dir>
chatmine teams extract --account <domain> --days 1 --out <dir>
chatmine whatsapp extract --days 3 --out <dir>
chatmine mail extract --account <domain> --days 2 --out <dir>
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

Mail: each email is a message, a thread is a conversation (the subject without `Re:`/`Fwd:`), and `to` and `cc` list the recipients. Quoted replies are cut from `contentText`. Trash and Junk are skipped. Newsletters and bulk mail (one-click unsubscribe, a single external sender) are left out by default; add `--include-bulk` to `extract` or `search` to keep them.

In WhatsApp the user's own messages have `from.mri == "self"`; WhatsApp does not extract edits, reactions or replies, and `contentHtml` is empty.

## Attachments

Every provider writes attachments in the same shape: `{name, contentType, contentUrl, path, url, available}`.

- `available: true`: `path` is an absolute local file you can open or read.
- `available: false`: the file is not on disk (Mail has not downloaded it, WhatsApp media was not kept, a Teams file was not fetched). `path` is `null`; `url` is the remote link when there is one, but it needs the app's session, so do not fetch it yourself.
- `extract` never downloads. `search` downloads Teams pasted images to a local cache so `path` opens. Mail and WhatsApp point to the files the app already stores. Inline images in emails (signatures, logos) are not listed.

## Search

Use `search` for pointed questions ("who sent the quote?", "where is the contract file?") and `extract` for broad analysis (summaries, catch-ups, counting). `search` is cheaper: it returns only the hits and a little context.

```bash
chatmine search "<term>" --days 3
chatmine search "<term>" --provider mail --account <domain> --include-bulk
chatmine search "<term>" --provider teams --since 2026-10-01 --from <name> --conversation <title> --has-attachments
```

- The match is a substring that ignores case and accents, over the text, conversation title, sender and attachment names.
- The window flags (`--days`, `--since`, `--until`) and `--account`/`--profile` are the same as `extract`; an account that does not exist in a provider is reported in `errors` for that provider only. `--context N` (default 2) adds N neighbours before and after each hit; `--limit` (default 50) caps the results, newest first.
- stdout is one JSON envelope: `{query, window, providers, total, truncated, errors, results}`. Each result has `provider`, `account`, `conversation: {id, title, type}`, `id`, `time`, `from`, `isSelf`, `text`, `attachments: [{name, type, path, url, available}]` and `context`. When `available` is true, `path` is a local file you can open (Teams pasted images are downloaded to a cache).
- `total` counts every hit; when it exceeds `--limit`, `truncated` is true: narrow the window or the filters, or raise `--limit`. Mail results also carry `to` and `cc`.
- A provider that fails goes to `errors` as `{provider, reason, hint}` and the others still answer. Exit code 0 means at least one provider answered (an empty `results` is not an error), 1 means every provider failed, 2 means a usage error (bad flag, unknown provider, bad date).

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
- Do not open the apps, log in or touch the Teams, WhatsApp or Mail databases yourself; chatmine does the reading.
