from pathlib import Path

from chatmine.providers.whatsapp.store import (
    SELF_ID,
    apple_to_iso,
    conversation_type,
    ms_to_apple,
    normalize_conversation,
    normalize_message,
)

GROUP = {"id": "123@g.us", "type": "group", "topic": "Família"}
DM = {"id": "5561999999999@s.whatsapp.net", "type": "oneOnOne", "topic": "Fulano"}
NAMES = {"111@lid": "Beltrano (agenda)"}
MEDIA = Path("/wa/Message")


def test_apple_epoch_roundtrip():
    assert apple_to_iso(0) == "2001-01-01T00:00:00.000Z"
    assert apple_to_iso(None) is None
    assert ms_to_apple(978307200_000) == 0


def test_conversation_type():
    assert conversation_type("123@g.us") == "group"
    assert conversation_type("55@s.whatsapp.net") == "oneOnOne"
    assert conversation_type("99@lid") == "oneOnOne"
    assert conversation_type("x@newsletter") == "other"


def test_normalize_conversation():
    conv = normalize_conversation(
        {"ZCONTACTJID": "123@g.us", "ZPARTNERNAME": "Família", "ZLASTMESSAGEDATE": 0,
         "ZCREATIONDATE": None, "member_count": 7}
    )
    assert conv == {
        "id": "123@g.us", "type": "group", "topic": "Família", "memberCount": 7,
        "createdAt": None, "lastMessageTime": "2001-01-01T00:00:00.000Z",
    }


def test_group_sender_resolved_from_names():
    row = {"Z_PK": 1, "ZSTANZAID": "ABC", "ZMESSAGEDATE": 0, "ZISFROMME": 0,
           "ZMESSAGETYPE": 0, "ZTEXT": "oi", "ZMEMBERJID": "111@lid", "ZFIRSTNAME": "Bel"}
    out = normalize_message(row, GROUP, NAMES, MEDIA)
    assert out["id"] == "ABC"
    assert out["from"] == {"mri": "111@lid", "displayName": "Beltrano (agenda)"}
    assert out["conversationTopic"] == "Família"
    assert out["contentText"] == "oi"
    assert out["messagetype"] == "text"
    assert "raw" not in out


def test_dm_sender_falls_back_to_topic_and_self():
    incoming = {"Z_PK": 2, "ZISFROMME": 0, "ZFROMJID": DM["id"], "ZMESSAGETYPE": 0}
    assert normalize_message(incoming, DM, {}, MEDIA)["from"]["displayName"] == "Fulano"
    mine = {"Z_PK": 3, "ZISFROMME": 1, "ZMESSAGETYPE": 0}
    assert normalize_message(mine, DM, {}, MEDIA)["from"]["mri"] == SELF_ID


def test_media_attachment_and_raw():
    row = {"Z_PK": 4, "ZISFROMME": 1, "ZMESSAGETYPE": 8, "ZTEXT": None,
           "media_title": "contrato.pdf", "media_path": "Media/x/contrato.pdf"}
    out = normalize_message(row, DM, {}, MEDIA, include_raw=True)
    assert out["id"] == "4"
    assert out["contentText"] == ""
    assert out["attachments"] == [
        {"name": "contrato.pdf", "contentType": "document",
         "contentUrl": "file:///wa/Message/Media/x/contrato.pdf"}
    ]
    assert out["raw"] == row
