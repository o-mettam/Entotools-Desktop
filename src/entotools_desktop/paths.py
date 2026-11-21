"""Where the app keeps its files.

    data:    the collection database (entotools.db) and settings
    cache:   HTTP response cache and map tiles (safe to delete)
    backups: automatic CSV backups (default ~/Documents/EntoTools Backups;
             the user can choose another folder in Phase 2)

ENTOTOOLS_HOME, if set, puts all three under one folder. Tests use it so they
never touch a real user's data.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs

APP_NAME = "EntoTools"


@dataclass(frozen=True)
class AppPaths:
    data: Path
    cache: Path
    backups: Path

    def ensure(self) -> "AppPaths":
        for p in (self.data, self.cache):
            p.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def database(self) -> Path:
        return self.data / "entotools.db"

    @property
    def http_cache(self) -> Path:
        return self.cache / "http_cache.db"

    @property
    def tiles(self) -> Path:
        return self.cache / "tiles"


def default_paths() -> AppPaths:
    home = os.environ.get("ENTOTOOLS_HOME")
    if home:
        root = Path(home)
        return AppPaths(root / "data", root / "cache", root / "backups")
    return AppPaths(
        data=Path(platformdirs.user_data_dir(APP_NAME, appauthor=False)),
        cache=Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False)),
        backups=Path(platformdirs.user_documents_dir()) / f"{APP_NAME} Backups",
    )
