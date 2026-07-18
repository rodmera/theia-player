from __future__ import annotations

import pytest
from theiaplayer.models import Song
from theiaplayer.app import TheIAPlayerApp


def _song(song_id: str, artist: str, title: str = "Track") -> Song:
    return Song(
        id=song_id,
        title=title,
        artist=artist,
        album="Album",
        duration=200,
    )


def test_reorder_for_artist_diversity_empty():
    # Call direct to avoid constructing the App and mutating class-level BINDINGS
    assert TheIAPlayerApp._reorder_for_artist_diversity(None, []) == []


def test_reorder_for_artist_diversity_no_repeats():
    songs = [
        _song("1", "Roxy Music"),
        _song("2", "Brian Eno"),
        _song("3", "Roxy Music"),
    ]
    # No consecutive repeats needed to be fixed, should preserve or alternate
    reordered = TheIAPlayerApp._reorder_for_artist_diversity(None, songs, last_artist="The Velvet Underground")
    artists = [s.artist for s in reordered]
    assert artists == ["Roxy Music", "Brian Eno", "Roxy Music"]


def test_reorder_for_artist_diversity_consecutive_repeats():
    songs = [
        _song("1", "Roxy Music"),
        _song("2", "Roxy Music"),
        _song("3", "Brian Eno"),
        _song("4", "David Bowie"),
    ]
    reordered = TheIAPlayerApp._reorder_for_artist_diversity(None, songs, last_artist="Roxy Music")
    artists = [s.artist for s in reordered]
    
    # Since last_artist was "Roxy Music", the first song should NOT be "Roxy Music" if possible
    assert artists[0] != "Roxy Music"
    
    # Ensure there are no consecutive same-artist tracks
    for i in range(len(artists) - 1):
        assert artists[i] != artists[i + 1]


def test_reorder_for_artist_diversity_fallback():
    songs = [
        _song("1", "Roxy Music"),
        _song("2", "Roxy Music"),
    ]
    # Only Roxy Music songs are available, fallback should just return them as-is
    reordered = TheIAPlayerApp._reorder_for_artist_diversity(None, songs, last_artist="Roxy Music")
    artists = [s.artist for s in reordered]
    assert artists == ["Roxy Music", "Roxy Music"]
