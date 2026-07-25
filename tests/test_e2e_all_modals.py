import pytest
from unittest.mock import AsyncMock, MagicMock
from theiaplayer.models import Song, Album, Playlist, SearchResults
from theiaplayer.app import TheIAPlayerApp
from theiaplayer import config as playerconfig
from theiaplayer.screens import (
    SpotlightModal,
    SignalPathModal,
    FocusModal,
    MoodsModal,
    AlbumVersionsModal,
    SearchModal,
)


@pytest.fixture
def dummy_app():
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.client = MagicMock()
    app.dirs = MagicMock()
    app.dirs.read_cache = MagicMock(return_value={
        "album": "The Pearl",
        "artist": "Harold Budd, Brian Eno",
        "year": "1984",
        "label": "EG Records",
        "genre": "Ambient",
        "producer": "Brian Eno, Daniel Lanois",
        "composers": "Harold Budd, Brian Eno",
        "key_musicians": "Harold Budd (piano), Brian Eno (synths)",
        "trivia": "Recording history at Grant Avenue Studios",
        "booklet_notes": "Detailed track-by-track breakdown notes",
        "status": "cached",
    })
    app.dirs.load_state = MagicMock(return_value={"pins": []})
    app.dirs.load_config = MagicMock(return_value={"profiles": {}})
    app.dirs.save_state = MagicMock()
    app.notify = MagicMock()
    app.copy_to_clipboard = MagicMock(return_value=True)
    app.push_screen = MagicMock()
    app.set_timer = MagicMock()
    app.refresh_cover_art = MagicMock()
    app.view = "all-songs"
    app._songs = [
        Song(id="s1", title="Song 1", artist="Artist 1", album="The Pearl", album_id="a1", bit_rate=1411, suffix="flac"),
        Song(id="s2", title="Song 2", artist="Artist 2", album="The Pearl (Remastered)", album_id="a2", bit_rate=320, suffix="mp3"),
    ]
    app._playlists = [
        Playlist(id="p1", name="Lectura", song_count=80),
        Playlist(id="p2", name="Música Suave", song_count=100),
        Playlist(id="p3", name="Género · Jazz", song_count=200),
    ]
    app._pcfg = {
        "filters": dict(playerconfig.DEFAULT_FILTERS),
        "replaygain": "album",
        "replaygain_preamp": 0.0,
        "gapless": "yes",
        "audio_exclusive": False,
    }
    app.player = MagicMock()
    app.player.get_audio_info = MagicMock(return_value={
        "codec": "flac",
        "samplerate": 96000,
        "format": "s32",
        "bitrate": 1411000,
        "device": "pipewire",
        "ao": "pipewire",
    })
    app.queue = MagicMock()
    app.queue.current = app._songs[0]
    app.queue.songs = list(app._songs)
    app.queue.shuffle = False
    return app


def test_action_copy_text_full_flow(dummy_app):
    dummy_app.action_copy_text()
    assert dummy_app.push_screen.called
    args = dummy_app.push_screen.call_args[0]
    modal = args[0]
    assert isinstance(modal, SpotlightModal)
    assert "Brian Eno" in modal._collaborators
    assert "Daniel Lanois" in modal._collaborators
    assert "Harold Budd" in modal._collaborators
    assert modal._booklet_text == "Detailed track-by-track breakdown notes"


def test_action_show_signal_path(dummy_app):
    dummy_app.action_show_signal_path()
    assert dummy_app.push_screen.called
    modal = dummy_app.push_screen.call_args[0][0]
    assert isinstance(modal, SignalPathModal)


def test_action_show_focus_filter(dummy_app):
    dummy_app.action_show_focus_filter()
    assert dummy_app.push_screen.called
    modal = dummy_app.push_screen.call_args[0][0]
    assert isinstance(modal, FocusModal)


def test_action_show_moods(dummy_app):
    dummy_app.action_show_moods()
    assert dummy_app.push_screen.called
    modal = dummy_app.push_screen.call_args[0][0]
    assert isinstance(modal, MoodsModal)


@pytest.mark.asyncio
async def test_action_show_album_versions_flow(dummy_app):
    albums = [
        Album(id="alb1", name="The Pearl", artist="Artist 1", year=1984),
        Album(id="alb2", name="The Pearl (Remastered)", artist="Artist 1", year=2005),
    ]
    dummy_app.client.search = AsyncMock(return_value=SearchResults(albums=albums))
    func = getattr(dummy_app.action_show_album_versions, "__wrapped__", dummy_app.action_show_album_versions)
    await func(dummy_app)
    assert dummy_app.push_screen.called
    modal = dummy_app.push_screen.call_args[0][0]
    assert isinstance(modal, AlbumVersionsModal)


def test_search_modal_initial_query_support():
    modal = SearchModal(initial_query="Daniel Lanois")
    assert modal._initial_query == "Daniel Lanois"
