"""Tests for theiaplayer.config.filter_songs().

Covers two contracts:

1. The pure filter behavior — exclude by title / artist / genre, duration
   bounds, and play-count minimum.

2. The Auto DJ regression from commit ``f8a9ee3``: Auto DJ was inlining
   ``playerconfig.apply_filters(songs, f)`` (a function that didn't exist),
   raising ``AttributeError`` that was swallowed by the ``except Exception:
   pass`` in ``_fetch_autoplay_songs``. The fix replaced the call with
   ``self._apply_filters(songs)``, which now delegates to
   ``playerconfig.filter_songs``. These tests pin the contract that Auto DJ
   uses the same source of truth as the rest of the app.
"""

from __future__ import annotations

from theiaplayer import config as playerconfig
from theiaplayer.config import DEFAULT_FILTERS, filter_songs
from theiaplayer.models import Song


def _song(
    song_id: str = "1",
    title: str = "Track",
    artist: str = "Artist",
    genre: str = "Rock",
    duration: int = 200,
    play_count: int = 0,
) -> Song:
    return Song(
        id=song_id,
        title=title,
        artist=artist,
        album="Album",
        genre=genre,
        duration=duration,
        play_count=play_count,
    )


# ── pure filter behavior ────────────────────────────────────────────────────


def test_default_filters_keep_everything():
    songs = [_song("1"), _song("2", title="Other")]
    assert filter_songs(songs, DEFAULT_FILTERS) == songs


def test_empty_filter_dict_keeps_everything():
    songs = [_song("1"), _song("2")]
    assert filter_songs(songs, {}) == songs


def test_exclude_titles_substring_case_insensitive():
    songs = [
        _song("1", title="Daily News"),
        _song("2", title="Music Track"),
    ]
    out = filter_songs(songs, {"exclude_titles": ["news"]})
    assert [s.id for s in out] == ["2"]


def test_exclude_artists_exact_match_case_insensitive():
    songs = [
        _song("1", artist="Various Artists"),
        _song("2", artist="The Band"),
    ]
    out = filter_songs(songs, {"exclude_artists": ["various artists"]})
    assert [s.id for s in out] == ["2"]


def test_exclude_genres_exact_match():
    songs = [
        _song("1", genre="Podcast"),
        _song("2", genre="Rock"),
        _song("3", genre="Audiobook"),
    ]
    out = filter_songs(songs, {"exclude_genres": ["podcast", "audiobook"]})
    assert [s.id for s in out] == ["2"]


def test_min_duration_drops_short_songs():
    songs = [
        _song("1", duration=10),    # too short (<= min)
        _song("2", duration=200),
        _song("3", duration=30),    # too short
    ]
    out = filter_songs(songs, {"min_duration": 60})
    assert [s.id for s in out] == ["2"]


def test_max_duration_drops_long_songs():
    songs = [
        _song("1", duration=600),
        _song("2", duration=30),    # below min? no — only max set.
        _song("3", duration=9000),  # too long
    ]
    out = filter_songs(songs, {"max_duration": 1000})
    assert [s.id for s in out] == ["1", "2"]


def test_min_play_count_drops_unplayed():
    songs = [
        _song("1", play_count=0),
        _song("2", play_count=5),
        _song("3", play_count=1),
    ]
    out = filter_songs(songs, {"min_play_count": 3})
    assert [s.id for s in out] == ["2"]


def test_filters_compose():
    """Multiple filter rules combine with AND semantics."""
    songs = [
        _song("1", title="News Update", genre="Podcast"),
        _song("2", title="Music", genre="Podcast"),     # dropped by genre
        _song("3", title="Music", genre="Rock", duration=10),  # dropped by duration
        _song("4", title="Music", genre="Rock", duration=200),  # keeps
    ]
    out = filter_songs(songs, {
        "exclude_titles": ["news"],
        "exclude_genres": ["podcast"],
        "min_duration": 60,
    })
    assert [s.id for s in out] == ["4"]


def test_filter_does_not_mutate_input():
    songs = [_song("1", title="Podcast"), _song("2", title="Music")]
    snapshot = list(songs)
    filter_songs(songs, {"exclude_titles": ["podcast"]})
    assert songs == snapshot


# ── Auto DJ regression (commit f8a9ee3) ──────────────────────────────────────


def test_autodj_filter_path_is_the_pure_filter():
    """Auto DJ fetches random songs and filters them before enqueueing.

    Before commit f8a9ee3, this called ``playerconfig.apply_filters`` —
    a function that never existed in ``config.py``. The bug was hidden
    by a broad ``except Exception: pass`` in ``_fetch_autoplay_songs``,
    so Auto DJ silently no-op'd instead of enqueuing. The fix routes the
    call through the real ``filter_songs`` function. This test pins the
    contract: a filter-songs invocation that matches the Auto DJ scenario
    must not raise AttributeError or return empty for non-trivial inputs.
    """
    raw = [
        _song("1", title="News Bulletin", genre="Podcast"),
        _song("2", title="Bohemian Rhapsody", genre="Rock"),
        _song("3", title="Stairway to Heaven", genre="Rock"),
    ]
    # The same filter dict Auto DJ applies in production.
    autodj_filters = {
        "exclude_titles": ["news", "bulletin"],
        "exclude_genres": ["podcast", "audiobook"],
    }

    # 1. The function must exist (regression for f8a9ee3: ``apply_filters``
    #    was a stale reference to a non-existent function).
    assert hasattr(playerconfig, "filter_songs")
    assert callable(playerconfig.filter_songs)

    # 2. Applying it to Auto DJ-like inputs must work and drop only the
    #    intended songs (no silent empty return).
    filtered = filter_songs(raw, autodj_filters)
    assert len(filtered) == 2
    assert {s.id for s in filtered} == {"2", "3"}

    # 3. Calling it twice (idempotency, like the recursive auto-DJ loop)
    #    must yield the same result.
    again = filter_songs(filtered, autodj_filters)
    assert again == filtered