import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from video_transcriptor import core, web
from video_transcriptor.models import Segment, Transcript

client = TestClient(web.create_app(save_dir=Path(tempfile.mkdtemp())), base_url="http://127.0.0.1:8765")


def test_index_and_options():
    assert "Video Transcriptor" in client.get("/").text
    opts = client.get("/api/options").json()
    assert opts["default_model"] == "small.en" and opts["max_minutes"] == 10


def test_transcribe_returns_text_and_files(monkeypatch):
    def fake(url, **kwargs):
        return Transcript([Segment(0, 1, "Hi.")], "en", "captions", "Title", url, 5)

    monkeypatch.setattr(core, "transcribe", fake)
    res = client.post("/api/transcribe", json={"url": "https://youtube.com/shorts/Xu-QfE_1ksk", "language": "en"})
    assert res.status_code == 200
    data = res.json()
    assert data["text"] == "Hi."
    assert data["files"]["srt"].startswith("1\n00:00:00,000")


def test_user_errors_are_shown(monkeypatch):
    def fail(url, **kwargs):
        raise core.TranscriptionError("too long", kind="video", title="Video too long")

    monkeypatch.setattr(core, "transcribe", fail)
    res = client.post("/api/transcribe", json={"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"})
    assert res.status_code == 422 and res.json()["detail"]["title"] == "Video too long" and res.json()["detail"]["kind"] == "video"


def test_input_validation():
    assert client.post("/api/transcribe", json={"url": "file:///etc/passwd"}).status_code == 400
    assert client.post("/api/transcribe", json={"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw", "language": "<script>"}).status_code in (400, 422)
    assert client.post("/api/transcribe", json={"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw", "model": "evil/repo"}).status_code == 400


def test_transcripts_are_saved_listed_and_deduplicated(monkeypatch, tmp_path):
    app_client = TestClient(web.create_app(save_dir=tmp_path), base_url="http://127.0.0.1:8765")
    calls = []

    def fake(url, **kwargs):
        calls.append(url)
        return Transcript([Segment(0, 1, "Saved text.")], "en", "captions", "My Video", url, 5)

    monkeypatch.setattr(core, "transcribe", fake)
    url = "https://www.youtube.com/watch?v=abc123defgh"
    data = app_client.post("/api/transcribe", json={"url": url}).json()
    assert data["saved_id"].endswith(" - My Video.txt")
    page = app_client.get("/api/transcripts").json()
    assert page["total"] == 1 and page["items"][0]["id"] == data["saved_id"]
    item = app_client.get("/api/transcript", params={"id": data["saved_id"]}).json()
    assert item["text"] == "Saved text." and item["link"] == url

    # Same video again: offered the existing transcript instead of a duplicate.
    again = app_client.post("/api/transcribe", json={"url": "https://youtu.be/abc123defgh"}).json()
    assert again["existing"]["id"] == data["saved_id"] and len(calls) == 1
    forced = app_client.post("/api/transcribe", json={"url": url, "force": True}).json()
    assert "saved_id" in forced and len(calls) == 2

    assert app_client.get("/api/transcripts", params={"q": "saved text"}).json()["total"] == 2
    assert app_client.get("/api/transcript", params={"id": "../../etc/passwd"}).status_code == 404
    assert app_client.delete("/api/transcript", params={"id": data["saved_id"]}).json()["ok"]
    assert app_client.get("/api/transcripts").json()["total"] == 1
    restored = app_client.post("/api/transcript/restore", json={"id": data["saved_id"]}).json()
    assert restored["id"] == data["saved_id"]


def test_dns_rebinding_and_cross_site_requests_are_blocked():
    assert client.get("/api/transcripts", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/transcripts", headers={"Host": "127.0.0.1:8765"}).status_code == 200
    assert client.get("/api/transcripts", headers={"Host": "[::1]:8765"}).status_code == 200
    res = client.post("/api/open-folder", json={}, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    ok = client.get("/api/options", headers={"Origin": "http://127.0.0.1:8765"})
    assert ok.status_code == 200


def test_security_headers():
    res = client.get("/")
    assert "frame-ancestors 'none'" in res.headers["content-security-policy"]
    assert res.headers["x-frame-options"] == "DENY"
    assert client.get("/openapi.json").status_code == 404
