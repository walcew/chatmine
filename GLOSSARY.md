# Glossário

Linguagem do domínio do `chatmine`. Só conceitos — nada de detalhe de implementação.

## Provider

Adaptador de **um** app de chat (Teams, Slack, Discord…). É dono do cliente da API
daquele app e da sua normalização. O núcleo (`core`) nunca enxerga o formato cru de
app nenhum — só o schema canônico que o Provider produz.

## Account

Uma identidade logada **dentro** de um Provider. No Teams é um tenant; no Slack seria
um workspace; no Discord, uma conta. Termo genérico sobre todos esses.

## Session

A credencial **viva e autenticada** de uma Account, obtida reaproveitando a sessão
local já autenticada do app (sem OAuth, sem consentimento corporativo novo). Tem um
instante de expiração e sabe qual é o "eu" (para distinguir mensagens próprias).

## ChromiumVault

Descritor de **onde e como** ler o cofre de cookies local de um app baseado em
Chromium: o serviço no Keychain, a raiz da instalação e a whitelist de cookies. A
decriptação em si é compartilhada e não conhece app nenhum — cada Provider só declara
esses dados.

## Conversation

Uma thread de conversa canônica — 1:1, grupo ou canal — independente de app.

## Message

Uma mensagem normalizada no **schema canônico**. Mantido em camelCase de propósito:
é o contrato que ferramentas de IA consomem a partir do `messages.jsonl`.

## Canonical schema

O formato independente de app que o `chatmine` grava em disco (`messages.jsonl`,
`conversations.json`). É o **contrato** entre a extração e qualquer análise.

## Extraction

Puxar as Conversations e Messages de uma Account numa janela de tempo para o diretório
de saída. O `chatmine` faz **só** extração — nunca análise. Classificar, resumir ou
cruzar com projetos é trabalho de um consumidor do schema canônico, fora deste projeto.
