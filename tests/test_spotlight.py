from __future__ import annotations

import pytest
from theiaplayer.screens import SpotlightModal


def test_spotlight_modal_initialization():
    modal = SpotlightModal(
        title="📌 ALBUM SPOTLIGHT",
        details_text="Test Album Details",
        copy_callback=None,
    )
    assert modal._title == "📌 ALBUM SPOTLIGHT"
    assert modal._details_text == "Test Album Details"


def test_spotlight_modal_copy_callback():
    copied_texts = []

    def callback(text):
        copied_texts.append(text)

    modal = SpotlightModal(
        title="📌 ALBUM SPOTLIGHT",
        details_text="Revolver details",
        copy_callback=callback,
    )
    modal.action_copy_and_dismiss()
    assert copied_texts == ["Revolver details"]
