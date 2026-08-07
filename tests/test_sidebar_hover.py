from __future__ import annotations

import pytest
from rich.text import Text
from theiaplayer.widgets import SidebarList, _format_sidebar_tooltip


def test_sidebar_tooltip_formatter():
    formatted = _format_sidebar_tooltip(
        title="Música Suave (Jazz & Bossa)",
        category="Ambiente / Modo",
        details="38 canciones  ·  2h 15m",
    )
    plain = formatted.plain
    assert "Música Suave (Jazz & Bossa)" in plain
    assert "Ambiente / Modo" in plain
    assert "38 canciones" in plain


def test_sidebar_list_set_tooltip_data():
    sl = SidebarList()
    data = {
        "pl:123": {
            "title": "Favoritas Recientes (2024-2026)",
            "category": "Playlist",
            "details": "142 canciones",
            "border_title": "playlist",
        }
    }
    sl.set_tooltip_data(data)
    assert sl._tooltip_data["pl:123"]["title"] == "Favoritas Recientes (2024-2026)"

