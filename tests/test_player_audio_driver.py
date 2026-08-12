"""Tests for theiaplayer.player.choose_audio_driver().

Documents the platform-default driver policy and locks it down so flipping
the default (e.g. ``pulse`` → ``pipewire``, see commit ``0a12bbd``) is a
visible, reviewable change rather than a buried ``if`` block.
"""

from __future__ import annotations

import pytest

from theiaplayer.player import choose_audio_driver


def test_explicit_ao_wins_on_linux():
    assert choose_audio_driver("alsa", platform="linux") == "alsa"


def test_explicit_ao_wins_on_macos():
    # Even though macOS would normally fall back to CoreAudio, an explicit
    # value must be honored verbatim (mpv accepts any valid ao string).
    assert choose_audio_driver("coreaudio", platform="darwin") == "coreaudio"


def test_explicit_ao_wins_on_windows():
    assert choose_audio_driver("wasapi", platform="win32") == "wasapi"


@pytest.mark.parametrize("platform", ["linux", "linux2", "freebsd"])
def test_non_darwin_platform_defaults_to_pipewire(platform):
    assert choose_audio_driver(None, platform=platform) == "pipewire"


def test_darwin_defaults_to_none_for_coreaudio_fallback():
    # None tells the Player to skip the ``ao=`` kwarg, letting mpv use CoreAudio.
    assert choose_audio_driver(None, platform="darwin") is None


def test_empty_string_ao_treated_as_explicit():
    """An explicit empty string is not the same as None — pass through."""
    assert choose_audio_driver("", platform="linux") == ""

from theiaplayer.player import resolve_audio_exclusive


def test_audio_exclusive_off_stays_off():
    assert resolve_audio_exclusive(False, "pipewire") is False
    assert resolve_audio_exclusive(False, "alsa") is False


def test_audio_exclusive_requires_alsa_driver():
    """Bit-perfect (exclusive) solo es factible sobre hardware ALSA directo."""
    assert resolve_audio_exclusive(True, "alsa") is True
    assert resolve_audio_exclusive(True, "alsa/hw:0,0") is True


def test_audio_exclusive_neutralized_on_shared_mixer():
    """pipewire/pulse (mezclador compartido, incl. Bluetooth) no soporta
    exclusividad — neutraliza para evitar el 'juego silencioso'."""
    assert resolve_audio_exclusive(True, "pipewire") is False
    assert resolve_audio_exclusive(True, "pulse") is False


def test_audio_exclusive_neutralized_on_no_driver():
    assert resolve_audio_exclusive(True, None) is False
