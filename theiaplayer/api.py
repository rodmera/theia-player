"""Async Subsonic/OpenSubsonic client for Navidrome.

Auth is the salted-token scheme: we store md5(password + salt) and the salt,
never the password itself. All calls go through `_get`, which unwraps the
`subsonic-response` envelope and raises `SubsonicError` on failure.

Cover art is fetched once and kept as files under the app cache dir, so art
for anything you've already looked at renders instantly and offline.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from pathlib import Path

import httpx

from theiaplayer.art import cmyk_to_rgb_safe
from theiaplayer.models import Album, Artist, Playlist, SearchResults, Song

API_VERSION = "1.16.1"
CLIENT_NAME = "theia-player"

class SubsonicError(Exception):
    """Server said no (bad auth, missing id, …)."""

def make_token(password: str) -> tuple[str, str]:
    """Return (token, salt) for the salted md5 auth scheme."""
    salt = secrets.token_hex(8)
    token = hashlib.md5((password + salt).encode()).hexdigest()
    return token, salt

def normalize_server(url: str) -> str:
    """Strip whitespace + trailing slash, prepend https:// if no scheme.

    Trims trailing slashes AFTER the scheme prefix so `http://` doesn't
    become `http:` (which would then be double-prefixed into the
    malformed `https://http:`)."""
    url = url.strip()
    if "://" in url:
        # Strip trailing slash only after the scheme marker
        scheme_end = url.index("://") + 3
        return url[:scheme_end] + url[scheme_end:].rstrip("/")
    url = url.rstrip("/")
    if url:
        url = "https://" + url
    return url

class SubsonicClient:
    def __init__(self, server: str, username: str, token: str, salt: str, art_dir: Path) -> None:
        self.server = normalize_server(server)
        self.username = username
        self._token = token
        self._salt = salt
        self._art_dir = art_dir
        self._http = httpx.AsyncClient(timeout=20, follow_redirects=True)

    async def close(self) -> None:
        await self._http.aclose()

    # ── plumbing ──────────────────────────────────────────────────────
    def _params(self, **extra) -> dict:
        params = {
            "u": self.username,
            "t": self._token,
            "s": self._salt,
            "v": API_VERSION,
            "c": CLIENT_NAME,
            "f": "json",
        }
        params.update({k: v for k, v in extra.items() if v is not None})
        return params

    async def _get(self, endpoint: str, **params) -> dict:
        url = f"{self.server}/rest/{endpoint}"
        resp = await self._http.get(url, params=self._params(**params))
        resp.raise_for_status()
        body = resp.json().get("subsonic-response", {})
        if body.get("status") != "ok":
            err = body.get("error", {})
            raise SubsonicError(err.get("message", f"error {err.get('code', '?')}"))
        return body

    # ── library ───────────────────────────────────────────────────────
    async def ping(self) -> dict:
        return await self._get("ping")

    async def get_artists(self) -> list[Artist]:
        body = await self._get("getArtists")
        artists: list[Artist] = []
        for index in body.get("artists", {}).get("index", []):
            for a in index.get("artist", []):
                artists.append(Artist.from_api(a))
        return artists

    async def get_artist_albums(self, artist_id: str) -> list[Album]:
        body = await self._get("getArtist", id=artist_id)
        return [Album.from_api(a) for a in body.get("artist", {}).get("album", [])]

    async def get_album_songs(self, album_id: str) -> list[Song]:
        body = await self._get("getAlbum", id=album_id)
        return [Song.from_api(s) for s in body.get("album", {}).get("song", [])]

    async def get_album_list(self, list_type: str, size: int = 500, offset: int = 0) -> list[Album]:
        """list_type: newest | recent | frequent | random | starred | alphabeticalByName"""
        body = await self._get("getAlbumList2", type=list_type, size=size, offset=offset)
        return [Album.from_api(a) for a in body.get("albumList2", {}).get("album", [])]

    async def get_playlists(self) -> list[Playlist]:
        body = await self._get("getPlaylists")
        return [Playlist.from_api(p) for p in body.get("playlists", {}).get("playlist", [])]

    async def create_playlist(self, name: str, song_ids: list[str]) -> None:
        await self._get("createPlaylist", name=name, songId=song_ids)

    async def add_to_playlist(self, playlist_id: str, song_ids: list[str]) -> None:
        await self._get("updatePlaylist", playlistId=playlist_id, songIdToAdd=song_ids)

    async def get_playlist_songs(self, playlist_id: str) -> list[Song]:
        body = await self._get("getPlaylist", id=playlist_id)
        return [Song.from_api(s) for s in body.get("playlist", {}).get("entry", [])]

    async def get_starred(self) -> SearchResults:
        body = await self._get("getStarred2")
        starred = body.get("starred2", {})
        return SearchResults(
            artists=[Artist.from_api(a) for a in starred.get("artist", [])],
            albums=[Album.from_api(a) for a in starred.get("album", [])],
            songs=[Song.from_api(s) for s in starred.get("song", [])],
        )

    async def search(self, query: str, limit: int = 20) -> SearchResults:
        body = await self._get(
            "search3",
            query=query,
            artistCount=limit,
            albumCount=limit,
            songCount=limit * 2,
        )
        result = body.get("searchResult3", {})
        return SearchResults(
            artists=[Artist.from_api(a) for a in result.get("artist", [])],
            albums=[Album.from_api(a) for a in result.get("album", [])],
            songs=[Song.from_api(s) for s in result.get("song", [])],
        )

    async def get_random_songs(self, size: int = 50) -> list[Song]:
        body = await self._get("getRandomSongs", size=size)
        return [Song.from_api(s) for s in body.get("randomSongs", {}).get("song", [])]

    async def get_similar_songs(self, song_id: str, size: int = 15) -> list[Song]:
        """Songs similar to the given track (LastFM-backed in Navidrome). Falls back to random."""
        try:
            body = await self._get("getSimilarSongs", id=song_id, count=size)
            songs = [Song.from_api(s) for s in body.get("similarSongs", {}).get("song", [])]
            if songs:
                return songs
        except Exception:
            pass
        return await self.get_random_songs(size=size)

    async def get_songs_by_albums(self, list_type: str, albums: int = 15) -> list[Song]:
        """Songs-first view of an album list: flatten the songs of the top N
        albums for `newest` / `recent` / `frequent`, keeping album order."""
        album_list = await self.get_album_list(list_type, size=albums)
        results = await asyncio.gather(
            *(self.get_album_songs(a.id) for a in album_list),
            return_exceptions=True,
        )
        songs: list[Song] = []
        for result in results:
            if isinstance(result, list):
                songs.extend(result)
        return songs

    async def get_all_songs(self, max_songs: int = 5000) -> list[Song]:
        """Every song in the library, paged through search3 with the empty
        query (the Navidrome/OpenSubsonic 'list everything' convention)."""
        songs: list[Song] = []
        page = 500
        while len(songs) < max_songs:
            body = await self._get(
                "search3",
                query='""',
                artistCount=0,
                albumCount=0,
                songCount=page,
                songOffset=len(songs),
            )
            batch = body.get("searchResult3", {}).get("song", [])
            songs.extend(Song.from_api(s) for s in batch)
            if len(batch) < page:
                break
        return songs[:max_songs]

    async def get_internet_radio_stations(self) -> list[dict]:
        """Fetch internet radio stations from Navidrome/Subsonic."""
        try:
            data = await self._get("getInternetRadioStations")
            stations = data.get("internetRadioStations", {}).get("station", [])
            return stations if isinstance(stations, list) else ([stations] if stations else [])
        except Exception:
            return []

    # ── playback side-channel ─────────────────────────────────────────
    def stream_url(self, song_id: str) -> str:
        params = "&".join(f"{k}={v}" for k, v in self._params(id=song_id).items())
        return f"{self.server}/rest/stream?{params}"

    async def scrobble(self, song_id: str, submission: bool) -> None:
        await self._get("scrobble", id=song_id, submission="true" if submission else "false")

    async def set_star(self, item_id: str, kind: str, star: bool) -> None:
        """kind: song | album | artist"""
        key = {"song": "id", "album": "albumId", "artist": "artistId"}[kind]
        await self._get("star" if star else "unstar", **{key: item_id})

    async def set_rating(self, song_id: str, rating: int) -> None:
        """rating: 0 (remove) or 1-5"""
        await self._get("setRating", id=song_id, rating=max(0, min(5, rating)))

    async def create_share(self, song_id: str) -> str:
        body = await self._get("createShare", id=song_id)
        shares = body.get("shares", {}).get("share", [])
        if not shares:
            raise SubsonicError("server returned no share object")
        url = shares[0].get("url", "")
        if not url:
            raise SubsonicError("share URL is empty")
        return url

    async def get_lyrics(
        self,
        song_id: str,
        artist: str = "",
        title: str = "",
        album: str = "",
        duration: float | None = None,
    ) -> list[dict]:
        """Return structured lyric lines.

        Tries:
        1. Local disk cache (~/.cache/theia-player/lyrics-{song_id}.json)
        2. Subsonic getLyricsBySongId (structured synced lyrics)
        3. Subsonic getLyrics (plain lyrics)
        4. LRCLIB public API (synced LRC lyrics)
        """
        cache_file = self._art_dir.parent / f"lyrics-{song_id}.json"
        if cache_file.exists():
            try:
                import json
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(cached, list) and cached:
                    return cached
            except Exception:
                pass

        # 1. Subsonic getLyricsBySongId
        try:
            body = await self._get("getLyricsBySongId", id=song_id)
            for entry in body.get("lyricsList", {}).get("structuredLyrics", []):
                lines = [{"start": l.get("start"), "value": l.get("value", "")} for l in entry.get("line", [])]
                if lines:
                    self._save_lyrics_cache(cache_file, lines)
                    return lines
        except Exception:
            pass

        # 2. Subsonic getLyrics
        try:
            params = {"id": song_id}
            if artist:
                params["artist"] = artist
            if title:
                params["title"] = title
            body = await self._get("getLyrics", **params)
            text = body.get("lyrics", {}).get("value", "")
            if text:
                lines = [{"start": None, "value": l} for l in text.splitlines() if l.strip()]
                if lines:
                    self._save_lyrics_cache(cache_file, lines)
                    return lines
        except Exception:
            pass

        # 3. LRCLIB Public Synced Lyrics Provider
        if artist and title:
            lines = await self._fetch_lrclib_lyrics(artist, title, album, duration)
            if lines:
                self._save_lyrics_cache(cache_file, lines)
                return lines

        return []

    def _save_lyrics_cache(self, cache_file: Path, lines: list[dict]) -> None:
        try:
            import json
            cache_file.write_text(json.dumps(lines, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    async def _fetch_lrclib_lyrics(
        self,
        artist: str,
        title: str,
        album: str = "",
        duration: float | None = None,
    ) -> list[dict]:
        import re
        _LRC_REGEX = re.compile(r"^\[(\d{1,2}):(\d{2}(?:\.\d{1,3})?)\](.*)")

        clean_title = re.sub(r"[\(\[\{].*?[\)\]\}]", "", title).strip() or title
        params = {"artist_name": artist, "track_name": clean_title}
        if album:
            params["album_name"] = album
        if duration and duration > 0:
            params["duration"] = str(int(duration))

        url = "https://lrclib.net/api/get"
        headers = {"User-Agent": "TheIA-Player/1.0 (https://github.com/rodmera/theia-player)"}
        try:
            r = await self._http.get(url, params=params, headers=headers, timeout=4.0)
            if r.status_code == 200:
                data = r.json()
                synced = data.get("syncedLyrics")
                if synced:
                    lines = []
                    for raw_line in synced.splitlines():
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        m = _LRC_REGEX.match(raw_line)
                        if m:
                            mins = int(m.group(1))
                            secs = float(m.group(2))
                            ms = int((mins * 60 + secs) * 1000)
                            val = m.group(3).strip()
                            lines.append({"start": ms, "value": val})
                        elif not raw_line.startswith("["):
                            lines.append({"start": None, "value": raw_line})
                    if lines:
                        return lines

                plain = data.get("plainLyrics")
                if plain:
                    return [{"start": None, "value": l} for l in plain.splitlines() if l.strip()]
        except Exception:
            pass
        return []

    # ── cover art ─────────────────────────────────────────────────────
    # 1200px: big enough that kitty/sixel terminals get a crisp image at
    # any panel size; halfcell terminals are bounded by cells either way
    def cached_art(self, cover_id: str, size: int = 1200) -> Path | None:
        path = self._art_dir / f"{cover_id.replace('/', '_')}-{size}"
        return path if path.exists() and path.stat().st_size > 0 else None

    async def cover_art(self, cover_id: str, size: int = 1200) -> Path:
        path = self._art_dir / f"{cover_id.replace('/', '_')}-{size}"
        if path.exists() and path.stat().st_size > 0:
            cmyk_to_rgb_safe(path)
            return path
        resp = await self._http.get(
            f"{self.server}/rest/getCoverArt",
            params=self._params(id=cover_id, size=size),
        )
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            body = resp.json().get("subsonic-response", {})
            err = body.get("error", {})
            raise SubsonicError(err.get("message", "no cover art"))
        if not resp.content:
            raise SubsonicError("empty cover art response")
        self._art_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(resp.content)
        cmyk_to_rgb_safe(tmp)
        tmp.replace(path)
        return path
