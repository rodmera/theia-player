import pytest
from theiaplayer.models import Playlist
from theiaplayer.screens import MoodsModal


def test_moods_modal_filters_ambient_playlists():
    playlists = [
        Playlist(id="1", name="Lectura", song_count=80),
        Playlist(id="2", name="Música Suave (Jazz & Blues)", song_count=100),
        Playlist(id="3", name="Sesión Nocturna", song_count=150),
        Playlist(id="4", name="Género · Alternative Rock", song_count=800),
        Playlist(id="5", name="Mezcla Aleatoria Dinámica", song_count=500),
    ]

    modal = MoodsModal(playlists)
    names = [p.name for p in modal._mood_playlists]

    assert "Lectura" in names
    assert "Música Suave (Jazz & Blues)" in names
    assert "Sesión Nocturna" in names
    assert "Mezcla Aleatoria Dinámica" in names
    assert "Género · Alternative Rock" not in names


def test_moods_modal_action_select_num():
    playlists = [
        Playlist(id="pl-lectura", name="Lectura", song_count=80),
    ]
    modal = MoodsModal(playlists)
    dismissed = []
    modal.dismiss = lambda val: dismissed.append(val)

    modal.action_select_num(1)

    assert len(dismissed) == 1
    assert dismissed[0] == {"playlist_id": "pl-lectura", "name": "Lectura"}
