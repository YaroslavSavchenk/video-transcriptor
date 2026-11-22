"""Real (unmocked) audio decoding, to catch incompatible faster-whisper / PyAV combinations."""

import math
import struct
import wave

from faster_whisper.audio import decode_audio


def test_faster_whisper_can_decode_audio_with_installed_pyav(tmp_path):
    path = tmp_path / "tone.wav"
    rate = 8000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) for i in range(rate)))
    audio = decode_audio(str(path), sampling_rate=16000)
    assert abs(len(audio) - 16000) < 400  # one second, resampled to 16 kHz
