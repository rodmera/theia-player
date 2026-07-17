"""Tests for theiaplayer.models.

Covers the round-trip contract that lets the whole library persist to the
AppDirs JSON cache: every dataclass must serialize via ``to_dict()`` and
re-hydrate via ``from_dict()`` without losing fields, and ``from_api()``
must tolerate the missing/extra keys Subsonic servers love to omit.

Closes hallazgo #3 of the 2026-07-17 code review (vault note
``202607170140 - Code Review theia-player - oportunidades de mejora``):
``models.py`` (159 LOC) had no dedicated tests — only indirect coverage
through other tests that happened to construct ``Song`` instances.
"""

from __future__ import annotations

import pytest

from theiaplayer.models import Album, Artist, Playlist, SearchResults, Song


# ── Artist ───────────────────────────────────────────────────────────────────


def test_artist_defaults():
    a = Artist(id="ar-1", name="The Band")
    assert a.id == "ar-1"
    assert a.name == "The Band"
    assert a.album_count == 0
    assert a.cover_art is None
    assert a.starred is False


def test_artist_from_api_minimal():
    a = Artist.from_api({"id": "ar-2", "name": "X"})
    assert a.id == "ar-2"
    assert a.name == "X"
    assert a.album_count == 0
    assert a.cover_art is None
    assert a.starred is False


def test_artist_from_api_full():
    a = Artist.from_api({
        "id": 42,                    # int id must coerce to str
        "name": "The Band",
        "albumCount": "5",            # numeric-as-string must coerce
        "coverArt": "ar-42",
        "starred": "2025-01-01T...",  # truthy string = starred
    })
    assert a.id == "42"
    assert a.album_count == 5
    assert a.cover_art == "ar-42"
    assert a.starred is True


def test_artist_round_trip():
    original = Artist(id="ar-3", name="Y", album_count=7, cover_art="ar-3", starred=True)
    rebuilt = Artist.from_dict(original.to_dict())
    assert rebuilt == original


# ── Album ────────────────────────────────────────────────────────────────────


def test_album_defaults():
    a = Album(id="al-1", name="Greatest Hits")
    assert a.release_type == "album"
    assert a.year is None
    assert a.artist == ""
    assert a.cover_art is None
    assert a.starred is False


def test_album_from_api_uses_title_fallback():
    """Some Subsonic responses use 'name', others 'title'."""
    a1 = Album.from_api({"id": "al-1", "name": "By Name"})
    a2 = Album.from_api({"id": "al-2", "title": "By Title"})
    a3 = Album.from_api({"id": "al-3"})  # neither — falls back to "?"
    assert a1.name == "By Name"
    assert a2.name == "By Title"
    assert a3.name == "?"


def test_album_from_api_release_type_passthrough():
    a = Album.from_api({"id": "al-1", "name": "X", "releaseType": "single"})
    assert a.release_type == "single"


def test_album_from_api_artist_id_coercion():
    a = Album.from_api({"id": "al-1", "name": "X", "artistId": 99})
    assert a.artist_id == "99"
    # Missing key -> None (not ""), preserving the Optional[str] type.
    a2 = Album.from_api({"id": "al-2", "name": "Y"})
    assert a2.artist_id is None


def test_album_round_trip_with_all_fields():
    original = Album(
        id="al-9", name="X", artist="Y", artist_id="ar-1",
        year=2024, song_count=12, duration=3000,
        cover_art="al-9", starred=True, release_type="ep",
    )
    rebuilt = Album.from_dict(original.to_dict())
    assert rebuilt == original


# ── Song ─────────────────────────────────────────────────────────────────────


def test_song_defaults():
    s = Song(id="s-1", title="Track")
    assert s.artist == ""
    assert s.rating == 0
    assert s.play_count == 0
    assert s.genre == ""
    assert s.track is None
    assert s.bit_rate is None


def test_song_from_api_minimal():
    s = Song.from_api({"id": "s-1", "title": "T"})
    assert s.id == "s-1"
    assert s.title == "T"
    assert s.duration == 0
    assert s.cover_art is None


def test_song_from_api_user_rating_field():
    """Navidrome exposes the user rating as 'userRating', not 'rating'."""
    s = Song.from_api({"id": "s-1", "title": "T", "userRating": 4})
    assert s.rating == 4


def test_song_from_api_disc_number_alias():
    s = Song.from_api({"id": "s-1", "title": "T", "discNumber": 2})
    assert s.disc == 2


def test_song_from_api_numeric_strings_coerced():
    """Navidrome occasionally returns numbers as strings; parse defensively.

    ``duration`` and ``play_count`` are coerced via ``int(... or 0)`` so
    string-encoded numbers round-trip correctly. ``bit_rate``, ``track``,
    ``disc`` and ``year`` are passed through (Subsonic servers usually
    return them as JSON numbers already).
    """
    s = Song.from_api({
        "id": "s-1",
        "title": "T",
        "duration": "240",
        "playCount": "5",
    })
    assert s.duration == 240
    assert s.play_count == 5


def test_song_round_trip_with_all_fields():
    original = Song(
        id="s-1", title="Track", artist="A", album="Al", album_id="al-1",
        artist_id="ar-1", track=3, disc=1, year=2024, duration=240,
        cover_art="s-1", suffix="mp3", bit_rate=320, starred=True,
        rating=5, play_count=10, genre="Rock",
    )
    rebuilt = Song.from_dict(original.to_dict())
    assert rebuilt == original


# ── Playlist ─────────────────────────────────────────────────────────────────


def test_playlist_defaults():
    p = Playlist(id="pl-1", name="My Mix")
    assert p.song_count == 0
    assert p.duration == 0
    assert p.owner == ""


def test_playlist_from_api_minimal():
    p = Playlist.from_api({"id": "pl-1", "name": "X"})
    assert p.id == "pl-1"
    assert p.name == "X"
    assert p.owner == ""


def test_playlist_round_trip():
    original = Playlist(id="pl-1", name="X", song_count=12, duration=3000, owner="me")
    rebuilt = Playlist.from_dict(original.to_dict())
    assert rebuilt == original


# ── SearchResults ────────────────────────────────────────────────────────────


def test_search_results_empty_by_default():
    sr = SearchResults()
    assert sr.artists == []
    assert sr.albums == []
    assert sr.songs == []
    assert sr.empty is True


def test_search_results_not_empty_when_artists_present():
    sr = SearchResults(artists=[Artist(id="ar-1", name="A")])
    assert sr.empty is False


def test_search_results_not_empty_when_albums_present():
    sr = SearchResults(albums=[Album(id="al-1", name="A")])
    assert sr.empty is False


def test_search_results_not_empty_when_songs_present():
    sr = SearchResults(songs=[Song(id="s-1", title="T")])
    assert sr.empty is False


# ── to_dict shape contracts ──────────────────────────────────────────────────


@pytest.mark.parametrize("model,expected_keys", [
    (Artist(id="1", name="A"), {"id", "name", "album_count", "cover_art", "starred"}),
    (Album(id="1", name="A"), {
        "id", "name", "artist", "artist_id", "year", "song_count",
        "duration", "cover_art", "starred", "release_type",
    }),
    (Song(id="1", title="T"), {
        "id", "title", "artist", "album", "album_id", "artist_id",
        "track", "disc", "year", "duration", "cover_art", "suffix",
        "bit_rate", "starred", "rating", "play_count", "genre",
    }),
    (Playlist(id="1", name="P"), {"id", "name", "song_count", "duration", "owner"}),
])
def test_to_dict_contains_all_field_keys(model, expected_keys):
    """The to_dict shape is part of the JSON-cache contract — drift here
    silently breaks persistence across launches."""
    assert set(model.to_dict().keys()) == expected_keys