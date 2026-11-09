import numpy as np
from meetingkit.audio.base import WavTrackWriter


def test_meter_follows_written_audio_without_changing_pcm(tmp_path):
    import wave
    path = tmp_path / 'track.wav'
    writer = WavTrackWriter(path, 16000)
    tone = np.full(1600, 3000, dtype=np.int16).tobytes()
    writer.write(tone)
    assert abs(writer.level - 0.5) < 1e-6
    assert writer.level_updated > 0
    silence = bytes(3200)
    writer.write(silence)
    assert writer.level == 0
    writer.close()
    with wave.open(str(path), 'rb') as audio:
        assert audio.readframes(3200) == tone + silence
