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


def test_limit_artist_frequency_caps_batch():
    candidates = [
        _song("1", "Travis", "Song 1"),
        _song("2", "Travis", "Song 2"),
        _song("3", "Travis", "Song 3"),
        _song("4", "Travis", "Song 4"),
        _song("5", "Keane", "Song 5"),
    ]
    filtered = TheIAPlayerApp._limit_artist_frequency(None, candidates, max_per_artist=2)
    travis_count = sum(1 for s in filtered if s.artist == "Travis")
    assert travis_count == 2
    assert len(filtered) == 3


def test_limit_artist_frequency_considers_queue():
    queue_songs = [
        _song("q1", "Travis"),
        _song("q2", "Travis"),
    ]
    candidates = [
        _song("1", "Travis", "Song 1"),
        _song("2", "Travis", "Song 2"),
        _song("3", "Keane", "Song 3"),
        _song("4", "Blur", "Song 4"),
    ]
    filtered = TheIAPlayerApp._limit_artist_frequency(None, candidates, max_per_artist=2, queue_songs=queue_songs)
    travis_count = sum(1 for s in filtered if s.artist == "Travis")
    # Queue count = 2, so Travis gets at most 1 additional song in the batch
    assert travis_count == 1


def test_limit_artist_frequency_queue_cap_exceeded():
    queue_songs = [
        _song("q1", "Travis"),
        _song("q2", "Travis"),
        _song("q3", "Travis"),
    ]
    candidates = [
        _song("1", "Travis", "Song 1"),
        _song("2", "Keane", "Song 2"),
    ]
    filtered = TheIAPlayerApp._limit_artist_frequency(None, candidates, max_per_artist=2, queue_songs=queue_songs)
    travis_count = sum(1 for s in filtered if s.artist == "Travis")
    assert travis_count == 0
    assert len(filtered) == 1
    assert filtered[0].artist == "Keane"


def test_limit_artist_frequency_fallback():
    queue_songs = [
        _song("q1", "Travis"),
        _song("q2", "Travis"),
        _song("q3", "Travis"),
    ]
    candidates = [
        _song("1", "Travis", "Song 1"),
        _song("2", "Travis", "Song 2"),
        _song("3", "Travis", "Song 3"),
    ]
    # Small library fallback ensures we still return tracks rather than halting playback completely
    filtered = TheIAPlayerApp._limit_artist_frequency(None, candidates, max_per_artist=2, queue_songs=queue_songs)
    assert len(filtered) == 2

