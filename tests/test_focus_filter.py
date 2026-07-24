import pytest
from theiaplayer.models import Song
from theiaplayer.config import filter_songs


def test_focus_filter_year_range():
    songs = [
        Song(id="1", title="Song 70s", year=1975),
        Song(id="2", title="Song 80s", year=1985),
        Song(id="3", title="Song 90s", year=1995),
    ]

    res = filter_songs(songs, {"min_year": 1980, "max_year": 1989})
    assert len(res) == 1
    assert res[0].title == "Song 80s"


def test_focus_filter_lossless_only():
    songs = [
        Song(id="1", title="FLAC Song", suffix="flac", bit_rate=1411),
        Song(id="2", title="MP3 Song", suffix="mp3", bit_rate=320),
    ]

    res = filter_songs(songs, {"lossless_only": True})
    assert len(res) == 1
    assert res[0].title == "FLAC Song"


def test_focus_filter_max_play_count():
    songs = [
        Song(id="1", title="Played Song", play_count=15),
        Song(id="2", title="Unplayed Song", play_count=0),
    ]

    res = filter_songs(songs, {"max_play_count": 0})
    assert len(res) == 1
    assert res[0].title == "Unplayed Song"
