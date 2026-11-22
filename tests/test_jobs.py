import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from video_transcriptor import core, web
from video_transcriptor.models import Segment, Transcript

URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def slow_transcribe(url, control, **kwargs):
    for i in range(100):
        control.stage("Transcribing…", i / 100)
        time.sleep(0.02)
    return Transcript([Segment(0, 1, "Done.")], "en", "speech-recognition", "Slow", url, 5, extra={"model": "x"})


def wait(client, job_id, until=("done", "error", "cancelled"), timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in until:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job still {job['status']}")


def make_client(tmp_path, monkeypatch, fn=slow_transcribe):
    monkeypatch.setattr(core, "transcribe", fn)
    return TestClient(web.create_app(save_dir=tmp_path), base_url="http://127.0.0.1:8765")


def test_job_reports_progress_and_finishes(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    job = client.post("/api/jobs", json={"url": URL}).json()
    time.sleep(0.3)
    running = client.get(f"/api/jobs/{job['id']}").json()
    assert running["status"] == "running" and running["stage"] == "Transcribing…" and 0 < running["progress"] < 1
    done = wait(client, job["id"])
    assert done["status"] == "done" and done["result"]["text"] == "Done." and done["result"]["saved_id"]


def test_job_can_be_cancelled_and_nothing_is_saved(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    job = client.post("/api/jobs", json={"url": URL}).json()
    time.sleep(0.2)
    client.post(f"/api/jobs/{job['id']}/cancel")
    assert wait(client, job["id"])["status"] == "cancelled"
    assert client.get("/api/transcripts").json()["total"] == 0


def test_only_one_job_at_a_time(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    first = client.post("/api/jobs", json={"url": URL}).json()
    second = client.post("/api/jobs", json={"url": "https://youtu.be/Xu-QfE_1ksk"})
    assert second.status_code == 409 and second.json()["detail"]["title"] == "Already busy"
    client.post(f"/api/jobs/{first['id']}/cancel")
    wait(client, first["id"])


def test_errors_and_crashes_end_up_in_the_job(tmp_path, monkeypatch):
    def fail(url, control, **kwargs):
        raise core.TranscriptionError("too long", kind="video", title="Video too long")

    client = make_client(tmp_path, monkeypatch, fail)
    job = wait(client, client.post("/api/jobs", json={"url": URL}).json()["id"])
    assert job["status"] == "error" and job["error"]["title"] == "Video too long"

    def crash(url, control, **kwargs):
        raise ZeroDivisionError("boom")

    monkeypatch.setattr(core, "transcribe", crash)
    job = wait(client, client.post("/api/jobs", json={"url": URL}).json()["id"])
    assert job["error"]["kind"] == "app" and "ZeroDivisionError" in job["error"]["technical"]


def test_stale_temp_dirs_are_cleaned_but_live_ones_kept():
    dead = Path(tempfile.mkdtemp(prefix=core.TEMP_PREFIX))
    (dead / ".owner").write_text("999999999")
    live = core._new_temp_dir()
    try:
        core.cleanup_stale_temp_dirs()
        assert not dead.exists() and live.exists()
    finally:
        import shutil
        shutil.rmtree(live, ignore_errors=True)
        shutil.rmtree(dead, ignore_errors=True)
