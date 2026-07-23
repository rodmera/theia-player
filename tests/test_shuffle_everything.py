import pytest
from unittest.mock import AsyncMock, MagicMock
from theiaplayer.models import Song
from theiaplayer.app import TheIAPlayerApp
from theiaplayer.playqueue import PlayQueue


def make_song(song_id: str, title: str, artist: str) -> Song:
    return Song(id=song_id, title=title, artist=artist)


@pytest.mark.asyncio
async def test_fetch_songs_for_shuffle_all_returns_shuffled():
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.client = MagicMock()
    app.dirs = MagicMock()

    songs = [
        make_song("1", "Song 1", "Artist A"),
        make_song("2", "Song 2", "Artist A"),
        make_song("3", "Song 3", "Artist A"),
        make_song("4", "Song 4", "Artist B"),
        make_song("5", "Song 5", "Artist B"),
        make_song("6", "Song 6", "Artist B"),
        make_song("7", "Song 7", "Artist C"),
        make_song("8", "Song 8", "Artist C"),
        make_song("9", "Song 9", "Artist C"),
        make_song("10", "Song 10", "Artist C"),
    ]
    app.client.get_all_songs = AsyncMock(return_value=list(songs))

    res_all = await app._fetch_songs_for_view("all-songs")
    assert res_all == songs

    res_shuffle = await app._fetch_songs_for_view("shuffle-all")
    assert len(res_shuffle) == len(songs)
    app.dirs.write_cache.assert_called_with("all-songs", {"songs": [s.to_dict() for s in songs]})


@pytest.mark.asyncio
async def test_shuffle_everything_syncs_central_pane_with_queue():
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.dirs = MagicMock()
    app.dirs.save_state = MagicMock()
    app.notify = MagicMock()
    app.view = "shuffle-all"
    app.queue = PlayQueue()
    app.queue.shuffle = False

    songs = [
        make_song("1", "Song 1", "Artist A"),
        make_song("2", "Song 2", "Artist B"),
        make_song("3", "Song 3", "Artist C"),
        make_song("4", "Song 4", "Artist D"),
    ]
    app._songs = list(songs)
    app.query_one = MagicMock()
    app._play_current = MagicMock()
    app._show_songs = MagicMock()
    app._tracks_title = MagicMock(return_value="shuffle everything")

    app._shuffle_everything()

    assert app.queue.shuffle is True
    # Central pane songs match the queue songs exactly
    assert app._songs == app.queue.songs


def test_play_songs_syncs_central_pane_for_any_playlist_when_shuffle_on():
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.view = "pl:123"
    app.queue = PlayQueue()
    app.queue.shuffle = True
    app._play_current = MagicMock()
    app._show_songs = MagicMock()
    app._tracks_title = MagicMock(return_value="Rock Playlist")

    playlist_songs = [
        make_song("1", "Track 1", "Band 1"),
        make_song("2", "Track 2", "Band 2"),
        make_song("3", "Track 3", "Band 3"),
        make_song("4", "Track 4", "Band 4"),
    ]

    app._play_songs(playlist_songs, start=0)

    # Queue started with Track 1 and shuffled rest
    assert app.queue.songs[0] == playlist_songs[0]
    # Central pane matches the queue exactly
    assert app._songs == app.queue.songs
    app._show_songs.assert_called_with(app.queue.songs, "Rock Playlist")


def test_toggle_shuffle_syncs_central_pane_on_and_off():
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.view = "pl:456"
    app.queue = PlayQueue()
    app.dirs = MagicMock()
    app.notify = MagicMock()
    app.query_one = MagicMock()
    app._render_queue = MagicMock()
    app._show_songs = MagicMock()
    app._tracks_title = MagicMock(return_value="Jazz Playlist")

    playlist_songs = [
        make_song("1", "Jazz 1", "Artist J"),
        make_song("2", "Jazz 2", "Artist J"),
        make_song("3", "Jazz 3", "Artist J"),
        make_song("4", "Jazz 4", "Artist J"),
    ]
    app.queue.set_songs(playlist_songs, start=0)
    app._songs = list(playlist_songs)

    # Toggle shuffle ON
    app.action_toggle_shuffle()
    assert app.queue.shuffle is True
    assert app._songs == app.queue.songs

    # Toggle shuffle OFF
    app.action_toggle_shuffle()
    assert app.queue.shuffle is False
    assert app._songs == playlist_songs
