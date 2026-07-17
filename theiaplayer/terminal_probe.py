"""Centralized terminal protocol detection.

Two TTY/ANSI workarounds used to live scattered across the codebase:

- ``art.py`` monkey-patched ``sixel.query_terminal_support`` and
  ``tgp.query_terminal_support`` to ``False`` to avoid ``textual_image``'s
  blocking terminal probe at import time.

- ``app.main()`` sniffed ``TERM_PROGRAM``/``TERM`` to force
  ``NAVITUI_ART=tgp`` on Ghostty/Kitty unless the user had set it explicitly.

Both behaviors now live here. ``probe()`` runs once at import time so any
consumer (``art.py``, ``app.py``, tests) gets the patching for free without
having to know the details. The function is idempotent.
"""

from __future__ import annotations

import os

_PROBED = False


def is_kitty_compatible() -> bool:
    """Return True if the running terminal is Ghostty or Kitty."""
    term = os.environ.get("TERM_PROGRAM", "").lower()
    if term in ("ghostty", "kitty"):
        return True
    return os.environ.get("TERM") == "xterm-kitty"


def current_protocol() -> str:
    """Return the resolved ``NAVITUI_ART`` value (``auto`` if unset)."""
    return os.environ.get("NAVITUI_ART", "auto").lower()


def _force_protocol_for_terminal() -> None:
    """On Ghostty/Kitty, force ``NAVITUI_ART=tgp`` unless the user set it."""
    if "NAVITUI_ART" in os.environ:
        return
    if is_kitty_compatible():
        os.environ["NAVITUI_ART"] = "tgp"


def _disable_textual_image_tty_queries() -> None:
    """Pre-import sixel/tgp and force their TTY probes to False.

    ``textual_image`` blocks on import to probe the terminal for sixel and
    kitty-graphics support. Forcing ``False`` keeps ``is_tty=True`` (so the
    rest of ``textual_image`` keeps working) while eliminating the startup
    hang. We pre-import the submodules so the patch lands before
    ``textual_image.widget`` reads them at import time.
    """
    try:
        import textual_image.renderable.sixel as _sixel
        import textual_image.renderable.tgp as _tgp
        _sixel.query_terminal_support = lambda: False
        _tgp.query_terminal_support = lambda: False
    except Exception:
        # textual_image not installed or layout changed — let art.py fall back
        # to its own try/except. Never let terminal probing break startup.
        pass


def probe() -> None:
    """Run terminal detection and patching. Idempotent and safe to re-call."""
    global _PROBED
    if _PROBED:
        return
    _PROBED = True
    _force_protocol_for_terminal()
    _disable_textual_image_tty_queries()


# Auto-run on import so callers don't have to remember to call probe().
probe()