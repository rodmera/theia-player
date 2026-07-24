"""NaviTui — a fast, animated terminal player for Navidrome.

Built on Textual and ricekit; playback via libmpv; cover art over the
kitty/sixel graphics protocols with a unicode fallback.
"""

from __future__ import annotations

# Importing terminal_probe runs Ghostty/Kitty detection and patches
# textual_image's blocking TTY probes. Importing it here ensures the patches
# land before any consumer of textual_image (e.g. theiaplayer.art).
from theiaplayer import terminal_probe  # noqa: F401

__version__ = "1.10.1"

def main() -> None:
    from theiaplayer.app import main as run

    run()
