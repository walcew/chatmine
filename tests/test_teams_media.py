from chatmine.providers.teams.media import cache_attachment

URL = "https://eu-api.asm.skype.com/v1/objects/0-neu-d4-abc123/views/imgo"


def _att(**extra):
    return {
        "name": "imagem", "contentType": None, "contentUrl": URL, "path": None,
        "url": URL, "available": False, **extra,
    }


class _Http:
    def __init__(self, fail=False):
        self.urls = []
        self.fail = fail

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise RuntimeError("403 em " + url)
        return b"\x89PNG-bytes", "image/png"


def test_downloads_once_and_reuses_cache(tmp_path):
    http = _Http()
    first = cache_attachment(_att(), http, tmp_path)
    second = cache_attachment(_att(), http, tmp_path)
    assert http.urls == [URL]
    assert first["available"] is True
    assert first["path"] == str(tmp_path / "0-neu-d4-abc123.png")
    assert second["path"] == first["path"] and second["available"] is True
    assert (tmp_path / "0-neu-d4-abc123.png").read_bytes() == b"\x89PNG-bytes"
    assert first["contentType"] == "image/png"
    # acerto de cache: o tipo vem da extensão, sem novo download
    assert second["contentType"] == "image/png"


def test_failure_marks_unavailable_without_raising(tmp_path, capsys):
    out = cache_attachment(_att(), _Http(fail=True), tmp_path)
    assert out["available"] is False and out["path"] is None
    assert list(tmp_path.iterdir()) == []
    assert "403" in capsys.readouterr().err  # a falha aparece no stderr


def test_sharepoint_attachment_is_left_alone(tmp_path):
    http = _Http()
    sp = _att(url="https://x.sharepoint.com/doc.pdf", contentUrl="https://x.sharepoint.com/doc.pdf")
    assert cache_attachment(sp, http, tmp_path) == sp
    assert http.urls == []


def test_ams_path_on_unknown_host_is_not_fetched(tmp_path):
    http = _Http()
    evil = "https://attacker.example/v1/objects/x/views/imgo"
    att = _att(url=evil, contentUrl=evil)
    assert cache_attachment(att, http, tmp_path) == att
    assert http.urls == []
