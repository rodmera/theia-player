import pytest
from unittest.mock import AsyncMock, MagicMock
from theiaplayer.models import Song
from theiaplayer.app import TheIAPlayerApp


def make_song(song_id: str, title: str, artist: str) -> Song:
    return Song(id=song_id, title=title, artist=artist)


@pytest.mark.asyncio
async def test_fetch_songs_for_shuffle_all_returns_shuffled():
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.client = MagicMock()
    app.dirs = MagicMock()

    # 10 test songs from same artists
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
    # Cache was written with canonical songs
    app.dirs.write_cache.assert_called_with("all-songs", {"songs": [s.to_dict() for s in songs]})


@pytest.mark.asyncio
async def test_shuffle_everything_syncs_central_pane_with_queue():
    app = TheIAPlayerApp.__new__(TheIAPlayerApp)
    app.dirs = MagicMock()
    app.dirs.save_state = MagicMock()
    app.notify = MagicMock()
    app.view = "shuffle-all"
    app.queue = MagicMock()
    app.queue.shuffle = False

    songs = [
        make_song("1", "Song 1", "Artist A"),
        make_song("2", "Song 2", "Artist B"),
        make_song("3", "Song 3", "Artist C"),
    ]
    app._songs = list(songs)
    app.query_one = MagicMock()
    app._play_songs = MagicMock()
    app._show_songs = MagicMock()
    app._tracks_title = MagicMock(return_value="shuffle everything")

    # Simulate queue after set_songs
    queued_songs = [songs[1], songs[0], songs[2]]
    app.queue.songs = queued_songs

    app._shuffle_everything()

    assert app.queue.shuffle is True
    app._show_songs.assert_called_with(queued_songs, "shuffle everything")
    assert app._songs == queued_songs
