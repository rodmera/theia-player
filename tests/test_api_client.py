"""HTTP-level tests for theiaplayer.api.SubsonicClient.

The client is async + httpx-based, so we drive it through `httpx.MockTransport`
to avoid any real network. We cover the contract-critical paths: param
construction, response envelope unwrapping, error translation, and the
JSON-to-model mappers that callers depend on.
"""

from __future__ import annotations

import json
import pytest
import pytest_asyncio
import httpx
from pathlib import Path

from theiaplayer.api import (
    API_VERSION,
    CLIENT_NAME,
    SubsonicClient,
    SubsonicError,
    make_token,
    normalize_server,
)


# ── pure helpers ──────────────────────────────────────────────────────


def test_make_token_returns_hex_salt_and_md5():
    token, salt = make_token("hunter2")
    # Salt: 8 random bytes → 16 hex chars
    assert len(salt) == 16
    assert all(c in "0123456789abcdef" for c in salt)
    # Token: md5(password + salt) → 32 hex chars
    assert len(token) == 32
    assert all(c in "0123456789abcdef" for c in token)


def test_make_token_matches_md5():
    """Cross-check the implementation: token must equal md5(password + salt)."""
    import hashlib
    token, salt = make_token("hello")
    assert token == hashlib.md5(b"hello" + salt.encode()).hexdigest()


def test_make_token_random_salt_per_call():
    """Two calls with the same password must yield different salts."""
    a, _ = make_token("same")
    b, _ = make_token("same")
    assert a != b


def test_normalize_server_strips_whitespace_and_trailing_slash():
    assert normalize_server("  https://example.com/  ") == "https://example.com"
    assert normalize_server("https://example.com///") == "https://example.com"


def test_normalize_server_prepends_https_when_missing_scheme():
    assert normalize_server("example.com") == "https://example.com"
    assert normalize_server("navidrome.local:4533") == "https://navidrome.local:4533"


def test_normalize_server_preserves_explicit_scheme():
    assert normalize_server("http://internal:8080") == "http://internal:8080"


def test_normalize_server_handles_empty_and_whitespace():
    """Empty input is passed through as-is (no request will be made)."""
    assert normalize_server("") == ""
    assert normalize_server("   ") == ""


def test_normalize_server_no_separator_does_not_split_scheme():
    """`://` already in the URL — don't double-prefix. The historical
    bug was that ``http://`` stripped to ``http:`` (no `://`), then the
    normalizer saw no `://` and prepended `https://`, producing the
    malformed ``https://http:``. Today's behaviour must round-trip."""
    # Both forms must recognise the scheme is already present
    assert normalize_server("http://") == "http://"  # or any non-broken result
    assert normalize_server("https://") == "https://"


# ── MockTransport harness ──────────────────────────────────────────────


class _MockAPI:
    """Async httpx MockTransport that returns canned envelopes.

    Records every request so tests can assert on the URL/params it
    generated. The default response is a subsonic-response OK envelope
    with the body passed at construction time.
    """

    def __init__(self, body: dict | None = None, status: int = 200,
                 status_str: str = "ok", error_msg: str = ""):
        self.requests: list[httpx.Request] = []
        body = body or {}
        if status_str == "ok":
            payload = {"subsonic-response": {"status": "ok", **body}}
        else:
            payload = {"subsonic-response": {
                "status": "failed",
                "error": {"code": 10, "message": error_msg},
            }}
        self._payload = payload
        self._status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status, json=self._payload)


@pytest_asyncio.fixture
async def client_factory(tmp_path):
    """Yields a function that builds a SubsonicClient bound to a custom
    MockTransport. Caller passes the mock; the client uses it for all
    outgoing requests via httpx.MockTransport."""
    clients: list[SubsonicClient] = []

    def _make(mock: _MockAPI) -> SubsonicClient:
        c = SubsonicClient(
            server="https://navidrome.test",
            username="rodmera",
            token="tok",
            salt="salt",
            art_dir=tmp_path / "art",
        )
        # Substitute the http client with one bound to our mock
        c._http = httpx.AsyncClient(
            transport=httpx.MockTransport(mock),
            timeout=20,
            follow_redirects=True,
        )
        clients.append(c)
        return c

    yield _make

    for c in clients:
        await c.close()


def _canonical_params(c: SubsonicClient, extra: dict) -> dict:
    """Rebuild the params the client should send for assertions."""
    return {
        "u": c.username,
        "t": c._token,
        "s": c._salt,
        "v": API_VERSION,
        "c": CLIENT_NAME,
        "f": "json",
        **{k: v for k, v in extra.items() if v is not None},
    }


# ── envelope unwrapping ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_unwraps_subsonic_response_envelope(client_factory):
    """The envelope's `status` is checked; the OTHER keys are returned."""
    mock = _MockAPI(body={"ping": "pong"})
    client = client_factory(mock)
    out = await client.ping()
    assert out["ping"] == "pong"
    assert out["status"] == "ok"


@pytest.mark.asyncio
async def test_get_ping_returns_ok_envelope(client_factory):
    """End-to-end: a successful ping returns the envelope's content."""
    mock = _MockAPI(body={"serverName": "Navidrome", "version": "0.54"})
    client = client_factory(mock)
    out = await client.ping()
    assert out["serverName"] == "Navidrome"


@pytest.mark.asyncio
async def test_get_raises_subsonic_error_on_failed_status(client_factory):
    mock = _MockAPI(status_str="failed", error_msg="bad credentials")
    client = client_factory(mock)
    with pytest.raises(SubsonicError, match="bad credentials"):
        await client.ping()


@pytest.mark.asyncio
async def test_get_raises_on_http_error_status(client_factory):
    """A 5xx response from the server should propagate as httpx.HTTPStatusError."""
    mock = _MockAPI(status=503)
    client = client_factory(mock)
    with pytest.raises(httpx.HTTPStatusError):
        await client.ping()


@pytest.mark.asyncio
async def test_get_sends_required_auth_params(client_factory):
    mock = _MockAPI(body={})
    client = client_factory(mock)
    await client.ping()
    qs = dict(mock.requests[0].url.params)
    assert qs["u"] == "rodmera"
    assert qs["t"] == "tok"
    assert qs["s"] == "salt"
    assert qs["v"] == API_VERSION
    assert qs["c"] == CLIENT_NAME
    assert qs["f"] == "json"


@pytest.mark.asyncio
async def test_get_drops_none_params(client_factory):
    """None-valued extras must be omitted (avoids noisy query strings)."""
    mock = _MockAPI(body={})
    client = client_factory(mock)
    await client._get("search3", query="x", artistCount=None, songCount=10)
    qs = dict(mock.requests[0].url.params)
    assert qs["query"] == "x"
    assert qs["songCount"] == "10"
    assert "artistCount" not in qs


@pytest.mark.asyncio
async def test_get_targets_rest_endpoint(client_factory):
    """The client must hit /rest/<endpoint> on the server."""
    mock = _MockAPI(body={})
    client = client_factory(mock)
    await client.ping()
    assert "/rest/ping" in str(mock.requests[0].url)


# ── library ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_artists_flattens_index_arrays(client_factory):
    payload = {
        "artists": {
            "index": [
                {"artist": [{"id": "a1", "name": "Alpha"}, {"id": "a2", "name": "Beta"}]},
                {"artist": [{"id": "a3", "name": "Gamma"}]},
            ]
        }
    }
    mock = _MockAPI(body=payload)
    client = client_factory(mock)
    artists = await client.get_artists()
    assert [a.id for a in artists] == ["a1", "a2", "a3"]
    assert [a.name for a in artists] == ["Alpha", "Beta", "Gamma"]


@pytest.mark.asyncio
async def test_get_artists_returns_empty_when_no_payload(client_factory):
    mock = _MockAPI(body={})
    client = client_factory(mock)
    assert await client.get_artists() == []


@pytest.mark.asyncio
async def test_get_artist_albums_passes_id(client_factory):
    mock = _MockAPI(body={"artist": {"album": [{"id": "al1", "name": "X"}]}})
    client = client_factory(mock)
    albums = await client.get_artist_albums("artist-99")
    assert len(albums) == 1
    assert albums[0].id == "al1"
    assert mock.requests[0].url.params["id"] == "artist-99"


@pytest.mark.asyncio
async def test_get_album_songs_maps_to_song_model(client_factory):
    payload = {"album": {"song": [{"id": "s1", "title": "Track 1"}]}}
    mock = _MockAPI(body=payload)
    client = client_factory(mock)
    songs = await client.get_album_songs("album-1")
    assert len(songs) == 1
    assert songs[0].id == "s1"
    assert songs[0].title == "Track 1"
    assert mock.requests[0].url.params["id"] == "album-1"


@pytest.mark.asyncio
async def test_get_playlists_maps_to_playlist_model(client_factory):
    payload = {"playlists": {"playlist": [{"id": "p1", "name": "Mix"}]}}
    mock = _MockAPI(body=payload)
    client = client_factory(mock)
    playlists = await client.get_playlists()
    assert len(playlists) == 1
    assert playlists[0].name == "Mix"


@pytest.mark.asyncio
async def test_get_playlist_songs_uses_entry_key(client_factory):
    """getPlaylist returns songs under the ``entry`` key (not ``song``)."""
    payload = {"playlist": {"entry": [{"id": "s1", "title": "Song"}]}}
    mock = _MockAPI(body=payload)
    client = client_factory(mock)
    songs = await client.get_playlist_songs("p1")
    assert len(songs) == 1
    assert songs[0].id == "s1"


@pytest.mark.asyncio
async def test_get_starred_returns_three_lists(client_factory):
    payload = {
        "starred2": {
            "artist": [{"id": "a1", "name": "X"}],
            "album": [{"id": "al1", "name": "Y"}],
            "song": [{"id": "s1", "title": "Z"}],
        }
    }
    mock = _MockAPI(body=payload)
    client = client_factory(mock)
    out = await client.get_starred()
    assert len(out.artists) == 1
    assert len(out.albums) == 1
    assert len(out.songs) == 1


@pytest.mark.asyncio
async def test_get_random_songs_maps_payload(client_factory):
    payload = {"randomSongs": {"song": [{"id": "s1", "title": "T"}]}}
    mock = _MockAPI(body=payload)
    client = client_factory(mock)
    songs = await client.get_random_songs(size=10)
    assert len(songs) == 1
    assert mock.requests[0].url.params["size"] == "10"


@pytest.mark.asyncio
async def test_get_similar_songs_returns_similar(client_factory):
    payload = {"similarSongs": {"song": [{"id": "s1", "title": "S"}]}}
    mock = _MockAPI(body=payload)
    client = client_factory(mock)
    songs = await client.get_similar_songs("seed", size=5)
    assert len(songs) == 1
    assert mock.requests[0].url.params["id"] == "seed"
    assert mock.requests[0].url.params["count"] == "5"


@pytest.mark.asyncio
async def test_get_similar_songs_falls_back_to_random_on_empty(client_factory):
    """When the server returns no similar songs, we fall back to
    getRandomSongs so Auto DJ still gets something playable."""
    mock = _MockAPI(body={"similarSongs": {}})  # no songs
    client = client_factory(mock)
    # The fallback fires inside get_similar_songs — first call returns
    # empty, then it tries get_random_songs. The mock returns OK but
    # without the randomSongs key, so we end up with []. Verify the
    # fallback path ran by counting requests.
    songs = await client.get_similar_songs("seed")
    assert songs == []
    # Two requests: getSimilarSongs + getRandomSongs
    assert len(mock.requests) == 2
    assert "getSimilarSongs" in str(mock.requests[0].url)
    assert "getRandomSongs" in str(mock.requests[1].url)


@pytest.mark.asyncio
async def test_get_similar_songs_falls_back_on_error(client_factory):
    """If getSimilarSongs raises (e.g. SubsonicError), the fallback
    fires — and if the fallback also fails, the SubsonicError bubbles
    up to the caller (Auto DJ catches it)."""
    mock = _MockAPI(status_str="failed", error_msg="not found")
    client = client_factory(mock)
    with pytest.raises(SubsonicError, match="not found"):
        await client.get_similar_songs("seed")
    assert len(mock.requests) == 2  # similar + random fallback


@pytest.mark.asyncio
async def test_get_album_list_passes_size_and_offset(client_factory):
    mock = _MockAPI(body={"albumList2": {"album": []}})
    client = client_factory(mock)
    await client.get_album_list("newest", size=20, offset=10)
    qs = dict(mock.requests[0].url.params)
    assert qs["type"] == "newest"
    assert qs["size"] == "20"
    assert qs["offset"] == "10"


@pytest.mark.asyncio
async def test_create_playlist_passes_name_and_song_ids(client_factory):
    mock = _MockAPI(body={})
    client = client_factory(mock)
    await client.create_playlist("Work", ["s1", "s2"])
    qs = mock.requests[0].url.params
    assert qs["name"] == "Work"
    # httpx serializes list params as repeated key=value
    assert httpx.QueryParams(qs).get_list("songId") == ["s1", "s2"]


@pytest.mark.asyncio
async def test_add_to_playlist_passes_song_ids_to_add(client_factory):
    mock = _MockAPI(body={})
    client = client_factory(mock)
    await client.add_to_playlist("p1", ["s1", "s2"])
    qs = mock.requests[0].url.params
    assert qs["playlistId"] == "p1"
    assert httpx.QueryParams(qs).get_list("songIdToAdd") == ["s1", "s2"]


@pytest.mark.asyncio
async def test_search_sets_three_count_limits(client_factory):
    mock = _MockAPI(body={"searchResult3": {}})
    client = client_factory(mock)
    await client.search("foo", limit=10)
    qs = dict(mock.requests[0].url.params)
    assert qs["query"] == "foo"
    assert qs["artistCount"] == "10"
    assert qs["albumCount"] == "10"
    assert qs["songCount"] == "20"  # songs get 2x the artist/album limit


@pytest.mark.asyncio
async def test_scrobble_sends_submission_flag(client_factory):
    mock = _MockAPI(body={})
    client = client_factory(mock)
    await client.scrobble("s1", submission=True)
    qs = dict(mock.requests[0].url.params)
    assert qs["id"] == "s1"
    assert qs["submission"] == "true"


@pytest.mark.asyncio
async def test_set_star_song_uses_id_param(client_factory):
    """Starring a song hits /rest/star with id=<id>."""
    mock = _MockAPI(body={})
    client = client_factory(mock)
    await client.set_star("song-1", "song", True)
    qs = dict(mock.requests[0].url.params)
    assert qs["id"] == "song-1"
    assert "/rest/star" in str(mock.requests[0].url)


@pytest.mark.asyncio
async def test_set_star_album_uses_album_id_param(client_factory):
    """Starring an album uses the albumId key (not id)."""
    mock = _MockAPI(body={})
    client = client_factory(mock)
    await client.set_star("album-1", "album", True)
    qs = dict(mock.requests[0].url.params)
    assert qs["albumId"] == "album-1"
    assert "id" not in qs


@pytest.mark.asyncio
async def test_unstar_passes_unstar_endpoint(client_factory):
    mock = _MockAPI(body={})
    client = client_factory(mock)
    await client.set_star("s1", "song", False)
    assert "/rest/unstar" in str(mock.requests[0].url)


@pytest.mark.asyncio
async def test_set_rating_clamps_to_zero_to_five(client_factory):
    """``max(0, min(5, rating))`` clamps out-of-range values."""
    mock = _MockAPI(body={})
    client = client_factory(mock)
    await client.set_rating("s1", 99)
    qs = dict(mock.requests[0].url.params)
    assert qs["rating"] == "5"  # clamped to max


@pytest.mark.asyncio
async def test_set_rating_negative_clamps_to_zero(client_factory):
    """Negative ratings are clamped to 0 (which Subsonic treats as 'unrate')."""
    mock = _MockAPI(body={})
    client = client_factory(mock)
    await client.set_rating("s1", -5)
    qs = dict(mock.requests[0].url.params)
    assert qs["rating"] == "0"


@pytest.mark.asyncio
async def test_get_internet_radio_stations(client_factory):
    """SubsonicClient.get_internet_radio_stations fetches station list."""
    mock = _MockAPI(body={
        "internetRadioStations": {
            "station": [
                {"id": "rad1", "name": "Radio Paradise", "streamUrl": "https://stream.radioparadise.com/flac"},
                {"id": "rad2", "name": "SomaFM Groove Salad", "streamUrl": "https://ice1.somafm.com/groovesalad-128-mp3"},
            ]
        }
    })
    client = client_factory(mock)
    stations = await client.get_internet_radio_stations()
    assert len(stations) == 2
    assert stations[0]["name"] == "Radio Paradise"
    assert stations[0]["streamUrl"] == "https://stream.radioparadise.com/flac"
    assert "/rest/getInternetRadioStations" in str(mock.requests[0].url)
