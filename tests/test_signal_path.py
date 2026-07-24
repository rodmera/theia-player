import pytest
from unittest.mock import MagicMock
from theiaplayer.models import Song
from theiaplayer.screens import SignalPathModal
from theiaplayer.player import Player, MPV_AVAILABLE


def test_player_get_audio_info():
    if not MPV_AVAILABLE:
        pytest.skip("mpv not available in environment")
    player = Player(on_position=lambda p, d: None, on_track_end=lambda f: None)
    info = player.get_audio_info()
    assert isinstance(info, dict)
    assert "codec" in info
    assert "ao" in info


def test_signal_path_modal_initialization():
    song = Song(
        id="s1",
        title="Test Title",
        artist="Test Artist",
        album="Test Album",
        year=2024,
        suffix="flac",
        bit_rate=1411,
    )
    audio_info = {
        "codec": "flac",
        "samplerate": 96000,
        "format": "s32",
        "bitrate": 1411000,
        "device": "alsa/hw:0",
        "ao": "pipewire",
    }
    opts = {
        "replaygain": "album",
        "replaygain_preamp": 4.0,
        "gapless": "yes",
        "eq_enabled": False,
        "audio_exclusive": True,
    }

    modal = SignalPathModal(song, audio_info, opts)
    text = modal._build_content().plain

    assert "Test Title — Test Artist" in text
    assert "FLAC (Lossless)" in text
    assert "96.0 kHz" in text
    assert "Bit-Perfect Direct" in text
