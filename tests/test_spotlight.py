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
