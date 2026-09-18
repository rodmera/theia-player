import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from textual.widgets import Input
from textual.widgets.option_list import Option
from theiaplayer.models import SearchResults, Song, Album, Artist
from theiaplayer.screens import SearchModal
from theiaplayer.app import TheIAPlayerApp
from theiaplayer.api import SubsonicClient


def _make_mock_app():
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.client = MagicMock()
    app.dirs = MagicMock()
    app.dirs.read_cache = MagicMock(return_value=None)
    app.dirs.write_cache = MagicMock()
    app.dirs.load_state = MagicMock(return_value={"pins": []})
    app.dirs.save_state = MagicMock()
    app.notify = MagicMock()
    app._connection_trouble = MagicMock()
    app._highlight_view = MagicMock()
    app._record_view_history = MagicMock()
    app._load_art = MagicMock()
    app._songs = []
    app._albums = []
    app._playlists = []
    app._selection = set()
    app.view = "all-songs"
    app.player = MagicMock()
    app.player.active = False
    app.queue = MagicMock()
    app.queue.current = None
    app.queue.songs = []
    app.queue.shuffle = False
    app._pcfg = {"filters": {}}
    return app


@pytest.mark.asyncio
async def test_search_modal_scrolling_does_not_overflow_box():
    """Regression test: `#search-box` must never scroll or clip `#search-results`.
    Moving down through options must increment `ol.scroll_offset.y` while keeping
    `box.scroll_offset.y == 0` and every highlighted item inside the visible viewport."""
    app = TheIAPlayerApp(client=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        sm = SearchModal()
        await app.push_screen(sm)

        songs = [Song(id=f"s{i}", title=f"Song {i}", artist="Artist", album="Album", duration=180) for i in range(35)]
        sm._results = SearchResults(songs=songs)
        sm._render_results()
        await pilot.pause()

        box = sm.query_one("#search-box")
        ol = sm.query_one("#search-results")
        assert box.scroll_offset.y == 0
        assert ol.region.height > 0

        ol.focus()
        for _ in range(25):
            await pilot.press("down")
            assert box.scroll_offset.y == 0, "Parent search-box must never overflow/scroll"
            vis_top = ol.scroll_offset.y
            vis_bottom = vis_top + ol.region.height
            assert vis_top <= ol.highlighted <= vis_bottom


@pytest.mark.asyncio
async def test_search_modal_category_tabs():
    """Test switching tabs filters results between all, songs, albums, and artists."""
    app = TheIAPlayerApp(client=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        sm = SearchModal()
        await app.push_screen(sm)

        songs = [Song(id=f"s{i}", title=f"Song {i}", artist="Artist", album="Album", duration=180) for i in range(5)]
        albums = [Album(id=f"a{i}", name=f"Album {i}", artist="Artist", year=2020) for i in range(3)]
        artists = [Artist(id=f"ar{i}", name=f"Artist {i}", album_count=2) for i in range(2)]
        sm._results = SearchResults(songs=songs, albums=albums, artists=artists)
        sm._render_results()
        await pilot.pause()

        ol = sm.query_one("#search-results")
        assert sm._active_tab == "all"
        # 5 songs + 3 albums + 2 artists + 3 headers = 13 options
        assert ol.option_count == 13

        # Switch to songs
        sm.action_next_tab()
        assert sm._active_tab == "songs"
        assert ol.option_count == 5

        # Switch to albums
        sm.action_next_tab()
        assert sm._active_tab == "albums"
        assert ol.option_count == 3

        # Switch to artists
        sm.action_next_tab()
        assert sm._active_tab == "artists"
        assert ol.option_count == 2

        # Cycle back to all
        sm.action_next_tab()
        assert sm._active_tab == "all"
        assert ol.option_count == 13

        # Test action_prev_tab
        sm.action_prev_tab()
        assert sm._active_tab == "artists"


@pytest.mark.asyncio
async def test_search_modal_queue_album_and_song():
    """Test queueing songs and albums from search results."""
    sm = SearchModal()
    sm.dismiss = MagicMock()
    songs = [Song(id="s1", title="Track 1", artist="Artist 1")]
    albums = [Album(id="a1", name="Record 1", artist="Artist 1")]
    sm._results = SearchResults(songs=songs, albums=albums)

    # Mock query_one to return a mock NavList
    mock_ol = MagicMock()
    sm.query_one = MagicMock(return_value=mock_ol)

    # Test song queue
    mock_ol.highlighted = 0
    mock_ol.get_option_at_index.return_value = Option("row", id="song:0")
    sm.action_queue_item(play_next=False)
    assert sm.dismiss.called
    assert sm.dismiss.call_args[0][0] == ("song-queue", songs[0], False)

    # Test album queue play next
    mock_ol.highlighted = 1
    mock_ol.get_option_at_index.return_value = Option("row", id="album:0")
    sm.action_queue_item(play_next=True)
    assert sm.dismiss.call_args[0][0] == ("album-queue", albums[0], True)


@pytest.mark.asyncio
async def test_search_client_lru_cache():
    """SubsonicClient.search must cache results by query to prevent redundant network calls."""
    client = SubsonicClient.__new__(SubsonicClient)
    client._search_cache = {}
    client._get = AsyncMock(return_value={
        "searchResult3": {
            "song": [{"id": "s1", "title": "Cached Song"}],
            "album": [],
            "artist": [],
        }
    })

    # First call hits _get
    res1 = await client.search("Radiohead")
    assert len(res1.songs) == 1
    assert res1.songs[0].title == "Cached Song"
    assert client._get.await_count == 1

    # Second call uses cache
    res2 = await client.search("radiohead")
    assert len(res2.songs) == 1
    assert client._get.await_count == 1  # Not called again
    assert res1 is res2


@pytest.mark.asyncio
async def test_app_action_enqueue_album_view():
    """In albums-* view, action_enqueue enqueues the highlighted album's tracks."""
    app = _make_mock_app()
    app.view = "albums-all"
    app._albums = [
        Album(id="a1", name="Kid A", artist="Radiohead"),
        Album(id="a2", name="Amnesiac", artist="Radiohead"),
    ]
    mock_ol = MagicMock()
    mock_ol.highlighted = 1
    app.query_one = MagicMock(return_value=mock_ol)
    app._enqueue_album = MagicMock()

    from unittest.mock import PropertyMock, patch

    mock_focused = MagicMock()
    mock_focused.id = "tracks-list"
    mock_focused.loading = False

    with patch.object(TheIAPlayerApp, "focused", new_callable=PropertyMock, return_value=mock_focused):
        app.action_enqueue(play_next=True)
        assert app._enqueue_album.called
        args, kwargs = app._enqueue_album.call_args
        assert args[0] == app._albums[1]
        assert kwargs["play_next"] is True
