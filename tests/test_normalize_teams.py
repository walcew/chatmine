import json

from chatmine.providers.teams.normalize import (
    html_to_text,
    normalize_conversation,
    normalize_message,
    parse_from,
)

RAW_MSG = {
    "id": "1700000000000",
    "conversationLink": "https://host/v1/users/ME/conversations/19:abc@thread.v2",
    "composetime": "2026-04-18T14:23:11.7850000Z",
    "from": "https://host/v1/users/8:orgid:11111111-2222-3333-4444-555555555555",
    "imdisplayname": "Fulano",
    "messagetype": "RichText/Html",
    "content": '<div>Olá <at id="0">Beltrano</at><br>tudo bem?</div>',
    "properties": {
        "emotions": [{"key": "like", "users": [{"mri": "x"}, {"mri": "y"}]}],
        "edittime": "123",
        "parentmessageid": "999",
    },
    "attachments": [
        {"name": "doc.pdf", "contentType": "application/pdf", "contentUrl": "https://x/doc.pdf"}
    ],
}


def test_normalize_message_canonical_shape():
    out = normalize_message(RAW_MSG, conv_topic="Projeto X")
    assert out["id"] == "1700000000000"
    assert out["from"]["mri"] == "8:orgid:11111111-2222-3333-4444-555555555555"
    assert out["from"]["displayName"] == "Fulano"
    assert out["conversationTopic"] == "Projeto X"
    assert out["contentText"] == "Olá @Beltrano\ntudo bem?"
    assert out["isEdited"] is True
    assert out["parentMessageId"] == "999"
    assert out["reactions"] == [{"key": "like", "count": 2}]
    assert len(out["attachments"]) == 1
    assert out["attachments"][0] == {
        "name": "doc.pdf", "contentType": "application/pdf", "contentUrl": "https://x/doc.pdf",
        "path": None, "url": "https://x/doc.pdf", "available": False,
    }


def test_normalize_message_raw_opt_in():
    assert "raw" not in normalize_message(RAW_MSG, conv_topic="")
    with_raw = normalize_message(RAW_MSG, conv_topic="", include_raw=True)
    assert with_raw["raw"] is RAW_MSG


def test_normalize_message_empty_defaults():
    out = normalize_message({}, conv_topic="")
    assert out["from"]["mri"] is None
    assert out["contentText"] == ""
    assert out["isEdited"] is False
    assert out["reactions"] == []
    assert out["attachments"] == []


def test_normalize_conversation_types():
    assert normalize_conversation({"id": "19:x@thread.v2"})["type"] == "group"
    assert normalize_conversation({"id": "19:x@unq.gbl.spaces"})["type"] == "oneOnOne"
    assert normalize_conversation({"id": "19:x@thread.tacv2"})["type"] == "channel"
    assert normalize_conversation({"id": "weird"})["type"] == "other"


def test_normalize_conversation_fields():
    conv = normalize_conversation(
        {
            "id": "19:abc@thread.v2",
            "threadProperties": {"topic": "Projeto X", "memberCount": 5},
            "lastMessage": {"composetime": "2026-04-18T14:23:11Z"},
        }
    )
    assert conv["topic"] == "Projeto X"
    assert conv["memberCount"] == 5
    assert conv["lastMessageTime"] == "2026-04-18T14:23:11Z"


def test_parse_from_variants():
    assert parse_from(None) is None
    assert parse_from("8:orgid:abc-123") == "8:orgid:abc-123"
    assert parse_from("https://h/users/orgid:abc-123") == "8:orgid:abc-123"


def test_html_to_text_collapses_whitespace():
    assert html_to_text("<div>a   b</div>") == "a b"
    assert html_to_text(None) == ""


AMS_URL = "https://eu-api.asm.skype.com/v1/objects/0-neu-d4-abc123/views/imgo"


def test_inline_ams_image_becomes_attachment():
    html = (
        f'<div>veja<img itemtype="http://schema.skype.com/AMSImage" src="{AMS_URL}" alt="imagem">'
        '<img itemtype="http://schema.skype.com/Emoji" src="https://x/emoji.png"></div>'
    )
    out = normalize_message({"content": html}, conv_topic="")
    assert out["attachments"] == [
        {
            "name": "imagem", "contentType": None, "contentUrl": AMS_URL, "path": None,
            "url": AMS_URL, "available": False,
        }
    ]


def test_attachments_keep_only_the_canonical_fields():
    raw = {
        "attachments": [
            {"name": "print.png", "contentType": "image/png", "contentUrl": AMS_URL},
            {"name": "doc.pdf", "contentType": "application/pdf",
             "contentUrl": "https://x.sharepoint.com/doc.pdf"},
        ]
    }
    ams, sharepoint = normalize_message(raw, conv_topic="")["attachments"]
    assert set(ams) == set(sharepoint) == {
        "name", "contentType", "contentUrl", "path", "url", "available"
    }
    assert sharepoint["available"] is False


def test_shared_files_in_properties_become_link_attachments():
    files = [
        {"fileName": "relatorio.xlsx", "objectUrl": "https://x.sharepoint.com/relatorio.xlsx",
         "fileInfo": {"shareUrl": "https://x.sharepoint.com/:x:/s"}},
        {"fileName": "sem-objeto.pdf", "fileInfo": {"shareUrl": "https://x.sharepoint.com/:b:/s"}},
    ]
    raw = {"content": "<p>segue</p>", "properties": {"files": json.dumps(files)}}
    xlsx, pdf = normalize_message(raw, conv_topic="")["attachments"]
    assert xlsx == {
        "name": "relatorio.xlsx", "contentType": None,
        "contentUrl": "https://x.sharepoint.com/relatorio.xlsx", "path": None,
        "url": "https://x.sharepoint.com/relatorio.xlsx", "available": False,
    }
    assert pdf["url"] == "https://x.sharepoint.com/:b:/s" and pdf["available"] is False


def test_malformed_properties_files_is_ignored():
    raw = {"content": "x", "properties": {"files": "{não é json"}}
    assert normalize_message(raw, conv_topic="")["attachments"] == []
