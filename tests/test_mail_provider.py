"""Provider mail contra uma árvore sintética que imita ~/Library (Mail + Accounts)."""

import json
import sqlite3
import time
from pathlib import Path

import pytest

from chatmine.__main__ import main
from chatmine.providers.mail import MailProvider

NOW = int(time.time())
RECENT = NOW - 3600
OLD = NOW - 86400 * 30
START_MS = (NOW - 86400) * 1000

ACCOUNTS = """
CREATE TABLE ZACCOUNT (Z_PK INTEGER PRIMARY KEY, ZPARENTACCOUNT INTEGER,
  ZACCOUNTDESCRIPTION VARCHAR, ZIDENTIFIER VARCHAR, ZUSERNAME VARCHAR);
INSERT INTO ZACCOUNT VALUES (1, NULL, 'eu@trabalho.example', 'EWS-0001', 'eu@trabalho.example');
INSERT INTO ZACCOUNT VALUES (2, NULL, 'Google', 'GOOGLE-PARENT', 'eu@gmail.example');
INSERT INTO ZACCOUNT VALUES (3, 2, NULL, 'GML-0001', NULL);
"""

INDEX = """
CREATE TABLE addresses (ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);
CREATE TABLE subjects (ROWID INTEGER PRIMARY KEY, subject TEXT);
CREATE TABLE mailboxes (ROWID INTEGER PRIMARY KEY, url TEXT, source INTEGER);
CREATE TABLE recipients (ROWID INTEGER PRIMARY KEY, message INTEGER, address INTEGER,
  type INTEGER, position INTEGER);
CREATE TABLE messages (ROWID INTEGER PRIMARY KEY, message_id INTEGER, global_message_id INTEGER,
  sender INTEGER, subject_prefix TEXT, subject INTEGER, date_sent INTEGER, date_received INTEGER,
  mailbox INTEGER, deleted INTEGER DEFAULT 0, conversation_id INTEGER, unsubscribe_type INTEGER);
CREATE TABLE attachments (ROWID INTEGER PRIMARY KEY AUTOINCREMENT, message INTEGER NOT NULL,
  attachment_id TEXT, name TEXT);
"""

ADDRESSES = {
    1: ("eu@trabalho.example", "Eu Trabalho"),
    2: ("ana@ext.example", "Ana"),
    3: ("bia@ext.example", ""),
    4: ("eu@gmail.example", ""),
    5: ("carlos@ext.example", "Carlos"),
    6: ("outro@pessoal.example", "Eu Pessoal"),
    7: ("spam@ext.example", ""),
    8: ("news@loja.example", "Loja"),
    9: ("lista@grupo.example", "Lista"),
}
MAILBOXES = {
    1: "ews://EWS-0001/Caixa%20de%20Entrada",
    2: "ews://EWS-0001/Itens%20Enviados",
    3: "ews://EWS-0001/Itens%20Exclui%CC%81dos",
    4: "ews://EWS-0001/Lixo%20Eletro%CC%82nico",
    5: "imap://GML-0001/%5BGmail%5D/Todos%20os%20e-mails",
    6: "imap://GML-0001/%5BGmail%5D/Spam",
    7: "imap://IMP-0001/INBOX",
    8: "imap://IMP-0001/Sent",
    9: "local://LOC-0001/Arquivo",
    10: "ews://EWS-0001/Clientes/Acme",
}

PLAIN_LATIN1 = (
    b"From: Ana <ana@ext.example>\r\nSubject: =?iso-8859-1?q?Cota=E7=E3o?=\r\n"
    b"MIME-Version: 1.0\r\nContent-Type: text/plain; charset=iso-8859-1\r\n"
    b"Content-Transfer-Encoding: quoted-printable\r\n\r\nOl=E1, segue a cota=E7=E3o.\r\n"
)
HTML_ONLY = (
    b"From: eu@trabalho.example\r\nSubject: RES: Cotacao\r\nMIME-Version: 1.0\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n\r\n"
    b"<html><head><style>p {color: red}</style></head>"
    b"<body><p>Recebido, obrigado.</p></body></html>\r\n"
)
MULTIPART = (
    b"From: Carlos <carlos@ext.example>\r\nSubject: Fw: Reuniao\r\nMIME-Version: 1.0\r\n"
    b'Content-Type: multipart/alternative; boundary="B"\r\n\r\n'
    b"--B\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: base64\r\n\r\n"
    b"UmV1bmnDo28gw6BzIDEwaC4=\r\n"
    b"--B\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
    b"<p>Reuni\xc3\xa3o <b>\xc3\xa0s 10h</b>.</p>\r\n"
    b"--B--\r\n"
)


def reply(body: str, ctype: str = "text/plain") -> bytes:
    head = f"From: Ana <ana@ext.example>\r\nSubject: Re: Plano\r\nContent-Type: {ctype}"
    return f"{head}; charset=utf-8\r\n\r\n{body}".encode()


OUTLOOK_PT = (
    "De: Carlos <carlos@ext.example>\nEnviado: segunda-feira, 5 de outubro de 2026 10:00\n"
    "Para: Ana\nAssunto: Plano\n\nTexto antigo."
)
OUTLOOK_EN = (
    "From: Carlos <carlos@ext.example>\nSent: Monday, October 5, 2026 10:00 AM\n"
    "To: Ana\nSubject: Plan\n\nOld text."
)
EMPTY_PLAIN = (
    "--B\r\nContent-Type: text/plain\r\n\r\n\r\n"
    "--B\r\nContent-Type: text/html\r\n\r\n<p>Novo.</p>\r\n--B--\r\n"
)
HTML_QUOTED = "<p>Novo.</p><blockquote><p>Texto antigo.</p></blockquote>"
# conversa 800: um estilo de citação por mensagem, cada uma com o texto novo "Novo."
QUOTED = {
    2001: "Novo.\n\nEm seg., 5 de out. de 2026, Carlos <c@ext.example>\nescreveu:\n> Antigo.",
    2002: "Novo.\n\nOn Mon, Oct 5, 2026 at 10:00 AM Carlos <c@ext.example> wrote:\n> Old text.",
    2003: f"Novo.\n\n{OUTLOOK_PT}",
    2004: f"Novo.\n\n{OUTLOOK_EN}",
    2005: "Novo.\n> Texto antigo.\n> Mais antigo.",
    2006: "Em seg., 5 de out. de 2026, Carlos escreveu:\n> Texto antigo.",  # tudo citado
    2008: "Novo.\n\nCarlos <mailto:c@ext.example>> escreveu:\n\nTexto antigo.",  # sem "Em"
    # CRLF, como nos .emlx reais
    2009: "Novo.\r\n\r\n5 out. 2026, Carlos <c@ext.example> escreveu:\r\n\r\nTexto antigo.",
    # Outlook Windows PT ("Enviada em:") e Outlook Mac PT/EN ("Data:"/"Date:")
    2010: "Novo.\n\nDe: Carlos <c@ext.example>\nEnviada em: segunda-feira, 5 de out. 10:00\n"
    "Para: Ana\nAssunto: Plano\n\nTexto antigo.",
    2011: "Novo.\n\nDe: Carlos <c@ext.example>\nData: seg., 5 de out. de 2026 10:00\n"
    "Para: Ana\nAssunto: Plano\n\nTexto antigo.",
    2012: "Novo.\n\nFrom: Carlos <c@ext.example>\nDate: Monday, October 5, 2026 at 10:00 AM\n"
    "To: Ana\nSubject: Plan\n\nOld text.",
}


def with_parts(*parts: str) -> bytes:
    head = (
        "From: Ana <ana@ext.example>\r\nSubject: Anexos\r\nMIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        "--B\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        '<p>Veja.</p><img src="cid:logo@x">\r\n'
    )
    return (head + "".join(f"--B\r\n{p}\r\n" for p in parts) + "--B--\r\n").encode()


PDF_PART = (
    "Content-Type: APPLICATION/PDF;\r\n\tname=relatorio.pdf\r\n"
    "Content-Disposition: ATTACHMENT;\r\n\tfilename=relatorio.pdf\r\n"
)
XLS_PART = (
    "Content-Type: application/vnd.ms-excel; name=planilha.xls\r\n"
    "Content-Disposition: attachment; filename=planilha.xls\r\n"
)
LOGO_PART = (
    "Content-Type: image/png; name=logo.png\r\nContent-Disposition: inline; filename=logo.png\r\n"
    "Content-Id: <logo@x>\r\n"
)
# sem Content-Disposition: só o cid: no HTML marca como inline
CID_PART = "Content-Type: image/png; name=assinatura.png\r\nContent-Id: <logo@x>\r\n"
# conversa 900: anexo baixado + inline; anexo não baixado (.partial.emlx); inline só por cid
ATTACHMENTS = {
    3001: [("2", "relatorio.pdf"), ("3", "logo.png")],
    3002: [("2", "planilha.xls")],
    3003: [("2", "assinatura.png")],
}
DOWNLOADED = {(3001, "2", "relatorio.pdf")}
PARTIAL = {12345, 3002}
SIMPLE = b"From: x\r\nSubject: s\r\nContent-Type: text/plain\r\n\r\ncorpo\r\n"

# ROWID, mailbox, conversation, message_id, sender, prefix, subject, date, to, cc, (path, body)
MESSAGES = [
    (
        1001,
        1,
        100,
        11,
        2,
        None,
        "Cotação",
        RECENT - 60,
        [1],
        [3],
        ("Caixa de Entrada", PLAIN_LATIN1),
    ),
    (1002, 2, 100, 12, 1, "RES: ", "Cotação", RECENT, [2], [], ("Itens Enviados", HTML_ONLY)),
    # mesma mensagem (message_id 11) arquivada numa subpasta: deve sumir na deduplicação
    (1003, 10, 100, 11, 2, None, "Cotação", RECENT - 60, [1], [3], ("Clientes.mbox/Acme", SIMPLE)),
    (
        12345,
        5,
        200,
        21,
        5,
        None,
        "Fw: Reunião",
        RECENT,
        [4],
        [],
        ("[Gmail].mbox/Todos os e-mails", MULTIPART),
    ),
    (1004, 3, 300, 31, 2, None, "Lixo", RECENT, [1], [], None),
    (1005, 6, 400, 41, 7, None, "Promo", RECENT, [4], [], None),
    (1006, 1, 500, 51, 2, None, "Antigo", OLD, [1], [], None),
    *(
        (row, 1, 800, row, 2, None, "Plano", RECENT + row, [1], [], ("Caixa de Entrada", reply(b)))
        for row, b in QUOTED.items()
    ),
    (
        2007, 1, 800, 2007, 2, None, "Plano", RECENT + 2007, [1], [],
        ("Caixa de Entrada", reply(HTML_QUOTED, "text/html")),
    ),
    # text/plain vazio ao lado do HTML: o texto vem do HTML
    (
        2013, 1, 800, 2013, 2, None, "Plano", RECENT + 2013, [1], [],
        ("Caixa de Entrada", reply(EMPTY_PLAIN, 'multipart/alternative; boundary="B"')),
    ),
    (3001, 1, 900, 3001, 2, None, "Anexos", RECENT + 1, [1], [],
     ("Caixa de Entrada", with_parts(PDF_PART, LOGO_PART))),
    (3002, 1, 900, 3002, 2, None, "Anexos", RECENT + 2, [1], [],
     ("Caixa de Entrada", with_parts(XLS_PART))),
    (3003, 1, 900, 3003, 2, None, "Anexos", RECENT + 3, [1], [],
     ("Caixa de Entrada", with_parts(CID_PART))),
    (7001, 8, 700, 71, 6, None, "Oi", RECENT, [2], [], ("Sent", SIMPLE)),
    # newsletter (1100) e thread de lista em que respondi (1200), ambas com unsubscribe one-click
    (1101, 1, 1100, 1101, 8, None, "Ofertas", RECENT, [1], [], None),
    (1201, 1, 1200, 1201, 9, None, "Debate", RECENT, [1], [], None),
    (1202, 1, 1200, 1202, 1, "Re: ", "Debate", RECENT + 1, [9], [], None),
]
# unsubscribe_type é bitmask (1 mailto, 2 http, 4 one-click); sem entrada fica NULL
UNSUBSCRIBE = {1101: 6, 1201: 7, 1202: 7}


def emlx(body: bytes) -> bytes:
    return f"{len(body)}\n".encode() + body + b"<?xml version='1.0'?><plist><dict/></plist>"


def emlx_path(mail: Path, url: str, mbox: str, rowid: int) -> Path:
    account = url.split("/")[2]
    digits = "/".join(reversed(str(rowid // 1000))) if rowid // 1000 else ""
    data = Path(mail, "V10", account, f"{mbox}.mbox", "STORE-UUID", "Data", digits, "Messages")
    suffix = ".partial.emlx" if rowid in PARTIAL else ".emlx"
    return data / f"{rowid}{suffix}"


@pytest.fixture
def library(tmp_path, monkeypatch):
    mail = tmp_path / "Library" / "Mail"
    (mail / "V10" / "MailData").mkdir(parents=True)
    (mail / "V2").mkdir()  # versão antiga: a descoberta deve preferir V10
    (tmp_path / "Library" / "Accounts").mkdir()
    with sqlite3.connect(tmp_path / "Library" / "Accounts" / "Accounts4.sqlite") as c:
        c.executescript(ACCOUNTS)
    with sqlite3.connect(mail / "V10" / "MailData" / "Envelope Index") as c:
        c.executescript(INDEX)
        c.executemany(
            "INSERT INTO addresses VALUES (?,?,?)", [(k, *v) for k, v in ADDRESSES.items()]
        )
        c.executemany("INSERT INTO mailboxes VALUES (?,?,NULL)", MAILBOXES.items())
        rid = 0
        for i, (row, mb, conv, mid, snd, pfx, subj, date, to, cc, file) in enumerate(MESSAGES):
            c.execute("INSERT INTO subjects VALUES (?,?)", (i, subj))
            c.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,0,?,?)",
                (row, mid, mid, snd, pfx, i, date, date, mb, conv, UNSUBSCRIBE.get(row)),
            )
            for kind, addrs in ((0, to), (1, cc)):
                for pos, addr in enumerate(addrs):
                    rid += 1
                    c.execute(
                        "INSERT INTO recipients VALUES (?,?,?,?,?)", (rid, row, addr, kind, pos)
                    )
            if file:
                path = emlx_path(mail, MAILBOXES[mb], file[0], row)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(emlx(file[1]))
                for aid, name in ATTACHMENTS.get(row, []):
                    c.execute("INSERT INTO attachments (message, attachment_id, name)"
                              " VALUES (?,?,?)", (row, aid, name))
                    if (row, aid, name) in DOWNLOADED:
                        att = path.parent.parent / "Attachments" / str(row) / aid / name
                        att.parent.mkdir(parents=True)
                        att.write_bytes(b"%PDF")
    monkeypatch.setenv("CHATMINE_MAIL_ROOT", str(mail))
    return mail


def messages(session, conv_id):
    provider = MailProvider()
    convs = {c["id"]: c for c in provider.list_conversations(session, START_MS)}
    return list(provider.iter_messages(session, convs[conv_id], START_MS))


def test_accounts_have_readable_labels(library):
    labels = {a.id: a.label for a in MailProvider().discover_accounts()}
    assert labels == {
        "EWS-0001": "eu@trabalho.example",  # descrição da conta
        "GML-0001": "eu@gmail.example",  # Gmail sem descrição: usa a conta-mãe
        "IMP-0001": "outro@pessoal.example",  # fora do Accounts4: remetente dos enviados
        "LOC-0001": "LOC-0001",  # sem nada: o UUID
    }


def test_conversations_skip_trash_spam_and_old(library):
    session = MailProvider().authenticate()
    convs = {c["id"]: c for c in MailProvider().list_conversations(session, START_MS)}
    assert set(convs) == {"100", "200", "700", "800", "900", "1200"}  # sem a newsletter 1100
    assert convs["100"]["topic"] == "Cotação"
    assert convs["100"]["type"] == "group"  # eu, Ana e Bia
    assert convs["200"]["topic"] == "Reunião"  # sem o "Fw:"
    assert convs["200"]["type"] == "oneOnOne"


def test_thread_messages_decoded_and_deduplicated(library):
    session = MailProvider().authenticate()
    msgs = messages(session, "100")
    assert [m["id"] for m in msgs] == ["1002", "1001"]  # mais nova primeiro, sem a duplicata
    sent, received = msgs
    assert received["contentText"] == "Olá, segue a cotação."
    assert received["from"] == {"mri": "ana@ext.example", "displayName": "Ana"}
    assert received["to"] == [{"mri": "eu@trabalho.example", "displayName": "Eu Trabalho"}]
    assert received["cc"] == [{"mri": "bia@ext.example", "displayName": "bia@ext.example"}]
    assert received["conversationTopic"] == "Cotação"
    assert sent["contentText"] == "Recebido, obrigado."
    assert "<p>Recebido, obrigado.</p>" in sent["contentHtml"]
    assert sent["from"]["mri"] in session.self_id


def test_multipart_prefers_plain_and_keeps_html(library):
    session = MailProvider().authenticate()
    [msg] = messages(session, "200")
    assert msg["contentText"] == "Reunião às 10h."
    assert "<b>às 10h</b>" in msg["contentHtml"]


def test_self_addresses_cover_all_accounts(library):
    session = MailProvider().authenticate()
    assert {"eu@trabalho.example", "eu@gmail.example", "outro@pessoal.example"} <= session.self_id


@pytest.mark.parametrize("selector", ["eu@gmail.example", "GML-0001", "EU@GMAIL.EXAMPLE"])
def test_account_selector_filters(library, selector):
    session = MailProvider().authenticate(selector)
    convs = MailProvider().list_conversations(session, START_MS)
    assert [c["id"] for c in convs] == ["200"]


def test_unknown_account_is_clear_error(library):
    with pytest.raises(ValueError, match="eu@gmail.example"):
        MailProvider().authenticate("ninguem@example")


def test_without_full_disk_access_error_has_hint(library, capsys):
    library.chmod(0)
    try:
        assert main(["mail", "accounts"]) == 2
    finally:
        library.chmod(0o755)
    assert "Full Disk Access" in capsys.readouterr().err


def test_mail_listed_in_providers(capsys):
    assert main(["providers"]) == 0
    assert "mail" in capsys.readouterr().out.split()


def test_quoted_history_is_cut_from_text_but_kept_in_html(library):
    session = MailProvider().authenticate()
    by_id = {m["id"]: m for m in messages(session, "800")}
    for rowid in [str(r) for r in QUOTED if r != 2006] + ["2007", "2013"]:
        assert by_id[rowid]["contentText"] == "Novo.", rowid
    assert by_id["2007"]["contentHtml"].count("Texto antigo.") == 1
    # tudo citado: mantém o corpo inteiro
    assert "Texto antigo." in by_id["2006"]["contentText"]


def test_attachments_have_path_and_availability(library):
    session = MailProvider().authenticate()
    by_id = {m["id"]: m for m in messages(session, "900")}
    [pdf] = by_id["3001"]["attachments"]  # logo.png é inline (Content-Disposition) e sai
    expected = emlx_path(library, MAILBOXES[1], "Caixa de Entrada", 3001)
    assert pdf["name"] == "relatorio.pdf"
    assert pdf["contentType"] == "application/pdf"
    att = expected.parent.parent / "Attachments" / "3001" / "2" / "relatorio.pdf"
    assert pdf["path"] == str(att)
    assert pdf["available"] is True
    # .partial.emlx: o Mail não baixou o arquivo
    [xls] = by_id["3002"]["attachments"]
    assert (xls["name"], xls["contentType"]) == ("planilha.xls", "application/vnd.ms-excel")
    assert xls["path"] is None
    assert xls["available"] is False
    # inline só por cid: referenciado no HTML
    assert by_id["3003"]["attachments"] == []
    assert by_id["3001"]["contentText"] == "Veja."


def _extracted_convs(tmp_path, *flags):
    out = tmp_path / "out"
    assert main(["mail", "extract", "--days", "1", "--out", str(out), *flags]) == 0
    return {c["id"] for c in json.loads((out / "conversations.json").read_text())}


def test_newsletter_excluded_unless_include_bulk(library, tmp_path):
    assert "1100" not in _extracted_convs(tmp_path)
    assert "1100" in _extracted_convs(tmp_path, "--include-bulk")


def test_list_thread_with_my_reply_is_kept(library, tmp_path):
    # as duas mensagens têm unsubscribe one-click, mas uma é minha
    assert "1200" in _extracted_convs(tmp_path)


def test_search_include_bulk_reaches_mail(library, capsys):
    def ids(*flags):
        assert main(["search", "Ofertas", "--provider", "mail", "--days", "1", *flags]) == 0
        return [r["id"] for r in json.loads(capsys.readouterr().out)["results"]]

    assert ids() == []
    assert ids("--include-bulk") == ["1101"]
