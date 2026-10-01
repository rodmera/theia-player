"""Pytest configuration for theia-player.

Aislamiento hermético de testing (Doctrina Antitaumatológica):
- Redirige AppDirs a un sandbox temporal para no contaminar ni depender de ~/.config/theia-player
  ni ~/.cache/theia-player del usuario real.
"""
from pathlib import Path
from unittest.mock import patch
import pytest
from ricekit.storage import AppDirs


@pytest.fixture(autouse=True)
def isolated_app_dirs(tmp_path, monkeypatch):
    """Aisla AppDirs para que cada test corra sobre un directorio temporal limpio."""
    real_init = AppDirs.__init__

    def mock_init(self, name: str) -> None:
        self.name = name
        sandbox = tmp_path / name
        self.state_file = sandbox / "state" / "state.json"
        self.cache_dir = sandbox / "cache"
        self.config_file = sandbox / "config" / "config.toml"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(AppDirs, "__init__", mock_init)
