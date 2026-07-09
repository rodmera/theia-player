"""Player configuration — player.toml alongside the server credentials file.

Parsed once at startup; never mutated at runtime (restart to apply changes).
Falls back to safe defaults if the file is absent or malformed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

DEFAULTS: dict = {
    "replaygain": "album",       # track | album | no
    "gapless": "yes",            # yes | no | weak
    "default_volume": 80,        # 0-130, -1 = restore last
    "desktop_notifications": True,
}


def load(config_dir: Path) -> dict:
    """Return merged config: defaults + whatever player.toml overrides."""
    cfg = dict(DEFAULTS)
    path = config_dir / "player.toml"
    if path.exists():
        try:
            overrides = tomllib.loads(path.read_text())
            cfg.update({k: v for k, v in overrides.items() if k in DEFAULTS})
        except Exception:
            pass  # malformed file → keep defaults
    return cfg


def write_default(config_dir: Path) -> None:
    """Write a commented default player.toml on first run."""
    path = config_dir / "player.toml"
    if path.exists():
        return
    config_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# theia-player — player settings\n"
        "# Restart the app after editing.\n\n"
        '# replaygain = "album"   # track | album | no\n'
        '# gapless    = "yes"     # yes | no | weak\n'
        "# default_volume = 80    # 0-130, -1 = restore last session\n"
        "# desktop_notifications = true\n"
    )
