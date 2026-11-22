import math
import struct
import wave

import av
import numpy as np
import pytest

from video_transcriptor import sandbox
from video_transcriptor.errors import TranscriptionError


def _tone(path, seconds=1, rate=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) for i in range(rate * seconds)))


def test_decodes_real_audio_in_a_separate_process(tmp_path):
    _tone(tmp_path / "a.wav", seconds=2)
    audio = sandbox.decode_audio(tmp_path / "a.wav", 600)
    assert audio.dtype == np.float32 and abs(len(audio) - 32000) < 400
    assert not list(tmp_path.glob("*.f32"))  # temp output removed


def test_garbage_file_gives_a_clear_error_not_a_crash(tmp_path):
    bad = tmp_path / "evil.mp4"
    bad.write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 50)
    with pytest.raises(TranscriptionError) as info:
        sandbox.decode_audio(bad, 600)
    assert info.value.title == "Can't read this video's audio"


def test_video_without_sound_is_reported(tmp_path):
    path = tmp_path / "silent.mp4"
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
        for _ in range(5):
            frame = av.VideoFrame.from_ndarray(np.zeros((32, 32, 3), np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    with pytest.raises(TranscriptionError) as info:
        sandbox.decode_audio(path, 600)
    assert info.value.title == "No sound in this video"


def test_output_size_is_capped(tmp_path):
    # 3 seconds of audio while only "0 seconds" are allowed (+60 s margin isn't enough at a
    # tiny limit): the child hits its file-size limit and the app reports a clean error.
    _tone(tmp_path / "long.wav", seconds=3)
    original = sandbox.SAMPLE_RATE
    try:
        sandbox.SAMPLE_RATE = 1  # makes the size limit ~240 bytes
        with pytest.raises(TranscriptionError):
            sandbox.decode_audio(tmp_path / "long.wav", 0)
    finally:
        sandbox.SAMPLE_RATE = original
