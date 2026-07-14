"""NaviTui — a fast, animated terminal player for Navidrome.

Built on Textual and ricekit; playback via libmpv; cover art over the
kitty/sixel graphics protocols with a unicode fallback.
"""

from __future__ import annotations

__version__ = "1.7.4"


def main() -> None:
    from theiaplayer.app import main as run

    run()
