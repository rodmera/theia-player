"""Tests for Auto DJ (Autoplay) context restriction.

Regla de negocio: la complementación de escucha (Auto DJ) SOLO debe operar
cuando se reproduce una Playlist. Cuando se reproduce un Álbum (o cualquier
otra vista), NO debe complementar la cola con canciones adicionales.
"""
from unittest.mock import AsyncMock, MagicMock
import pytest
from theiaplayer.app import TheIAPlayerApp
from theiaplayer.models import Album, Song
from theiaplayer.playqueue import PlayQueue


def _make_app(client=None) -> TheIAPlayerApp:
    mock_player = MagicMock()
    mock_player.get_audio_devices.return_value = []
    mock_player.get_current_audio_device.return_value = "auto"
    app = TheIAPlayerApp(client=client or MagicMock(), player=mock_player)
    app.queue = PlayQueue()
    return app


def test_is_playlist_playback_album_source():
    app = _make_app()
    app._playback_source = "album"
    app.view = "recent-albums"
    assert app._is_playlist_playback() is False


def test_is_playlist_playback_single_album_songs():
    app = _make_app()
    app._playback_source = "other"
    # All songs belong to the same album
    songs = [
        Song(id="s1", title="Track 1", artist="Saiko", album="Informe Saiko", album_id="alb1"),
        Song(id="s2", title="Track 2", artist="Saiko", album="Informe Saiko", album_id="alb1"),
    ]
    app.queue.set_songs(songs, 0)
    assert app._is_playlist_playback() is False


def test_is_playlist_playback_playlist():
    app = _make_app()
    app._playback_source = "playlist"
    app.view = "pl:123"
    assert app._is_playlist_playback() is True


def test_is_playlist_playback_view_playlist():
    app = _make_app()
    app._playback_source = ""
    app.view = "pl:123"
    assert app._is_playlist_playback() is True


def test_check_autoplay_does_not_fire_for_album():
    app = _make_app()
    app._playback_source = "album"
    songs = [
        Song(id="s1", title="Track 1", artist="Saiko", album="Informe Saiko", album_id="alb1"),
        Song(id="s2", title="Track 2", artist="Saiko", album="Informe Saiko", album_id="alb1"),
    ]
    app.queue.set_songs(songs, 1)  # Only 1 song remaining
    app._fetch_autoplay_songs = MagicMock()

    app._check_autoplay()

    # Must NOT call _fetch_autoplay_songs
    app._fetch_autoplay_songs.assert_not_called()


def test_check_autoplay_fires_for_playlist():
    app = _make_app()
    app._playback_source = "playlist"
    songs = [
        Song(id="s1", title="Track 1", artist="Artist 1", album="Album 1"),
        Song(id="s2", title="Track 2", artist="Artist 2", album="Album 2"),
    ]
    app.queue.set_songs(songs, 0)  # remaining <= 3
    app._fetch_autoplay_songs = MagicMock()

    app._check_autoplay()

    # Must call _fetch_autoplay_songs
    app._fetch_autoplay_songs.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_autoplay_songs_aborts_if_switched_to_album():
    app = _make_app()
    app._playback_source = "album"  # User switched to album
    app._is_playlist_playback = MagicMock(return_value=False)
    app.client.get_similar_songs = AsyncMock(return_value=[Song(id="s99", title="Extra", artist="Extra")])

    worker = app._fetch_autoplay_songs()
    await worker.wait()

    assert len(app.queue.songs) == 0
