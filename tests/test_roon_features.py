import pytest
from unittest.mock import MagicMock
from theiaplayer.models import Album
from theiaplayer.screens import AlbumVersionsModal, SpotlightModal


def test_album_versions_modal_initialization():
    albums = [
        Album(id="alb1", name="The Pearl", year=1984, song_count=11),
        Album(id="alb2", name="The Pearl (2005 Digital Remaster)", year=2005, song_count=11),
    ]

    modal = AlbumVersionsModal("The Pearl", albums)
    assert modal._base_title == "The Pearl"
    assert len(modal._versions) == 2


def test_spotlight_modal_collaborator_and_booklet_actions():
    modal = SpotlightModal(
        title="📌 ALBUM SPOTLIGHT & CRÉDITOS ROON",
        details_text="Overview text",
        copy_callback=None,
        collaborators=["Brian Eno", "Daniel Lanois"],
        booklet_text="Detailed track-by-track booklet notes",
    )

    # Test collaborator search action
    dismissed = []
    modal.dismiss = lambda val: dismissed.append(val)
    modal.action_search_collaborator(2)
    assert len(dismissed) == 1
    assert dismissed[0] == {"action": "search", "query": "Daniel Lanois"}

    # Test booklet toggle action
    assert modal._showing_booklet is False
    modal.action_toggle_booklet()
    assert modal._showing_booklet is True
