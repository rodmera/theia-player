from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from theiaplayer.screens import SpotlightModal
from theiaplayer.models import Song, Album
from theiaplayer.app import TheIAPlayerApp


def test_spotlight_modal_initialization():
    modal = SpotlightModal(
        title="📌 ALBUM SPOTLIGHT",
        details_text="Test Album Details",
        copy_callback=None,
    )
    assert modal._title == "📌 ALBUM SPOTLIGHT"
    assert modal._details_text == "Test Album Details"


def test_spotlight_modal_copy_callback():
    copied_texts = []

    def callback(text):
        copied_texts.append(text)

    modal = SpotlightModal(
        title="📌 ALBUM SPOTLIGHT",
        details_text="Revolver details",
        copy_callback=callback,
    )
    modal.action_copy_and_dismiss()
    assert copied_texts == ["Revolver details"]


@pytest.mark.asyncio
async def test_fetch_songs_for_home_view_spotlights_playing_album():
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.client = MagicMock()
    app.dirs = MagicMock()
    app.dirs.read_cache = MagicMock(return_value={
        "trivia": "The Smiths trivia",
        "producer": "The Smiths",
        "composers": "Morrissey",
        "key_musicians": "Johnny Marr",
    })
    app._fetch_spotlight_trivia_async = MagicMock()

    playing_song = Song(
        id="s1",
        title="Girlfriend in a Coma",
        artist="The Smiths",
        album="Strangeways Here We Come",
        album_id="alb-smiths",
    )

    app.queue = MagicMock()
    app.queue.current = playing_song

    album_songs = [playing_song, Song(id="s2", title="A Rush and a Push", artist="The Smiths")]
    app.client.get_album_songs = AsyncMock(return_value=album_songs)

    res = await app._fetch_songs_for_view("home")

    assert res == album_songs
    app.client.get_album_songs.assert_called_with("alb-smiths")
    assert app._current_spotlight_album_id == "alb-smiths"
    assert app._current_spotlight_text == "The Smiths trivia"


@pytest.mark.asyncio
async def test_fetch_songs_for_home_view_fallback_when_no_playing_song():
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.client = MagicMock()
    app.dirs = MagicMock()
    app.dirs.read_cache = MagicMock(return_value={
        "trivia": "Sade trivia",
        "producer": "Sade",
        "composers": "Adu",
        "key_musicians": "Sade Adu",
    })
    app._fetch_spotlight_trivia_async = MagicMock()

    app.queue = MagicMock()
    app.queue.current = None

    fallback_album = Album(id="alb-fallback", name="Lovers Rock", artist="Sade")
    app.client.get_album_list = AsyncMock(return_value=[fallback_album])

    album_songs = [Song(id="s10", title="By Your Side", artist="Sade")]
    app.client.get_album_songs = AsyncMock(return_value=album_songs)

    res = await app._fetch_songs_for_view("home")

    assert res == album_songs
    app.client.get_album_list.assert_called_with("recent", size=30)
    app.client.get_album_songs.assert_called_with("alb-fallback")
    assert app._current_spotlight_album_id == "alb-fallback"


def test_prefetch_upcoming_spotlights_dispatches_new_albums_in_queue():
    """Verify that _prefetch_upcoming_spotlights inspects queue.songs and dispatches
    prefetch workers for unique uncached upcoming albums."""
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.dirs = MagicMock()
    app._spotlight_memory_cache = {}
    app._prefetch_single_spotlight_async = MagicMock()

    s1 = Song(id="1", title="Track 1", album_id="alb-1", album="Album 1", artist="Artist 1")
    s2 = Song(id="2", title="Track 2", album_id="alb-2", album="Album 2", artist="Artist 2")
    s3 = Song(id="3", title="Track 3", album_id="alb-2", album="Album 2", artist="Artist 2")  # duplicate album
    s4 = Song(id="4", title="Track 4", album_id="alb-3", album="Album 3", artist="Artist 3")

    from theiaplayer.playqueue import PlayQueue
    app.queue = PlayQueue()
    app.queue.set_songs([s1, s2, s3, s4], 0)

    # Mock _read_spotlight so alb-2 and alb-3 are treated as uncached
    app.dirs.read_cache = MagicMock(return_value=None)

    app._prefetch_upcoming_spotlights()

    # Must be called for alb-2 and alb-3 (not alb-1 which is playing, and deduped for alb-2)
    assert app._prefetch_single_spotlight_async.call_count == 2
    called_album_ids = [c.args[0] for c in app._prefetch_single_spotlight_async.call_args_list]
    assert called_album_ids == ["alb-2", "alb-3"]


def test_prefetch_upcoming_spotlights_skips_already_cached_albums():
    """If an upcoming album already has complete metadata in cache, it must not trigger Gemini."""
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.dirs = MagicMock()
    app._spotlight_memory_cache = {
        "alb-cached": {
            "trivia": "Already cached review",
            "producer": "Known Producer",
            "status": "cached",
        }
    }
    app._prefetch_single_spotlight_async = MagicMock()

    s1 = Song(id="1", title="Track 1", album_id="alb-1", album="Album 1", artist="Artist 1")
    s2 = Song(id="2", title="Track 2", album_id="alb-cached", album="Cached Album", artist="Cached Artist")

    from theiaplayer.playqueue import PlayQueue
    app.queue = PlayQueue()
    app.queue.set_songs([s1, s2], 0)

    app._prefetch_upcoming_spotlights()

    assert app._prefetch_single_spotlight_async.call_count == 0
