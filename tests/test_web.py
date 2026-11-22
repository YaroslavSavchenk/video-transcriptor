from fastapi.testclient import TestClient

from video_transcriptor import core, web
from video_transcriptor.models import Segment, Transcript

client = TestClient(web.create_app())


def test_index_and_options():
    assert "Video Transcriptor" in client.get("/").text
    opts = client.get("/api/options").json()
    assert opts["default_model"] == "small.en" and opts["max_minutes"] == 10


def test_transcribe_returns_text_and_files(monkeypatch):
    def fake(url, **kwargs):
        return Transcript([Segment(0, 1, "Hi.")], "en", "captions", "Title", url, 5)

    monkeypatch.setattr(core, "transcribe", fake)
    res = client.post("/api/transcribe", json={"url": "https://youtube.com/shorts/x", "language": "en"})
    assert res.status_code == 200
    data = res.json()
    assert data["text"] == "Hi."
    assert data["files"]["srt"].startswith("1\n00:00:00,000")


def test_user_errors_are_shown(monkeypatch):
    def fail(url, **kwargs):
        raise core.TranscriptionError("too long")

    monkeypatch.setattr(core, "transcribe", fail)
    res = client.post("/api/transcribe", json={"url": "https://youtube.com/x"})
    assert res.status_code == 422 and res.json()["detail"] == "too long"


def test_input_validation():
    assert client.post("/api/transcribe", json={"url": "file:///etc/passwd"}).status_code == 400
    assert client.post("/api/transcribe", json={"url": "https://x.com", "language": "<script>"}).status_code in (400, 422)
    assert client.post("/api/transcribe", json={"url": "https://x.com", "model": "evil/repo"}).status_code == 400
