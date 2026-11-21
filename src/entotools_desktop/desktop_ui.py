"""Native dialogs and OS hand-offs (server.Dialogs) backed by pywebview.

pywebview marshals create_file_dialog onto the GUI thread itself, so these
are safe to call from the HTTP server's worker threads.
"""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

import webview


class WebviewDialogs:
    def __init__(self, last_dir=lambda: None):
        self.window: webview.Window | None = None
        self._last_dir = last_dir

    def _first(self, result):
        if not result:
            return None
        return result if isinstance(result, str) else result[0]

    def save_path(self, suggested_name: str) -> str | None:
        start = self._last_dir() or str(Path.home() / "Documents")
        return self._first(self.window.create_file_dialog(
            webview.FileDialog.SAVE, directory=start, save_filename=suggested_name))

    def choose_folder(self, start: str) -> str | None:
        return self._first(self.window.create_file_dialog(webview.FileDialog.FOLDER, directory=start))

    def open_url(self, url: str) -> None:
        webbrowser.open(url)

    def reveal(self, path: str) -> None:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)  # noqa: S606 — opens the backup folder in Explorer
        else:
            subprocess.Popen(["xdg-open", path])
