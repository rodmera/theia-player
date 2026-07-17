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