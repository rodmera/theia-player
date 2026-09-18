import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock
from theiaplayer.models import Album, Song
from theiaplayer.app import TheIAPlayerApp, ALBUM_VIEW_LABELS, ALBUM_LIST_TYPES


def _dummy_app():
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


def test_album_view_constants():
    assert set(ALBUM_VIEW_LABELS) == {
        "albums-all", "albums-newest", "albums-frequent", "albums-random", "albums-starred",
    }
    assert ALBUM_LIST_TYPES["albums-all"] == "alphabeticalByName"
    assert ALBUM_LIST_TYPES["albums-newest"] == "newest"
    assert ALBUM_LIST_TYPES["albums-frequent"] == "frequent"
    assert ALBUM_LIST_TYPES["albums-random"] == "random"
    assert ALBUM_LIST_TYPES["albums-starred"] == "starred"


def test_load_albums_view_is_plain_coroutine():
    """Regression: _load_view awaits _load_albums_view, so it must NOT be a
    @work worker (a Worker object can't be awaited → TypeError crash)."""
    assert inspect.iscoroutinefunction(TheIAPlayerApp._load_albums_view)


@pytest.mark.asyncio
async def test_load_albums_view_renders_rows():
    app = _dummy_app()
    app.view = "albums-all"
    app.client.get_album_list = AsyncMock(return_value=[
        Album(id="a1", name="Mezzanine", artist="Massive Attack", year=1998, song_count=22),
    ])
    app.query_one = MagicMock()
    app._fill = MagicMock()

    await app._load_albums_view("albums-all")

    assert app._fill.called
    opts = app._fill.call_args[0][1]
    assert opts[0].id == "alb:a1"
    assert "Mezzanine" in str(opts[0])


@pytest.mark.asyncio
async def test_load_albums_view_uses_correct_list_type():
    app = _dummy_app()
    app.view = "albums-random"
    app.client.get_album_list = AsyncMock(return_value=[])
    app.query_one = MagicMock()
    app._fill = MagicMock()

    await app._load_albums_view("albums-random")

    app.client.get_album_list.assert_awaited_once_with("random", size=500)


@pytest.mark.asyncio
async def test_track_selected_album_plays_album():
    """Regression: selecting an album row (id alb:<aid>) must trigger _play_album."""
    app = _dummy_app()
    album = Album(id="a1", name="Mezzanine", artist="Massive Attack")
    app._albums = [album]
    app._play_album = MagicMock()

    class Event:
        option = MagicMock()
        option.id = "alb:a1"

    app._track_selected(Event())

    app._play_album.assert_called_once_with(album)