"""Entry point: `python -m entotools_desktop` or the `entotools` script.

Starts the local server (server.App), then opens the native window on the
one-time launch URL that hands the window its session cookie.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys

import webview

from . import __version__
from .desktop_ui import WebviewDialogs
from .paths import default_paths
from .server import App


def setup_logging(paths) -> None:
    paths.ensure()
    handler = logging.handlers.RotatingFileHandler(paths.cache / "entotools.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if "--debug" in sys.argv:
        root.addHandler(logging.StreamHandler())
        root.setLevel(logging.DEBUG)


def main() -> None:
    paths = default_paths()
    setup_logging(paths)
    dialogs = WebviewDialogs()
    app = App(paths, dialogs=dialogs)
    dialogs._last_dir = lambda: app.store.get_setting("last_save_dir")
    app.start()
    logging.getLogger(__name__).info("EntoTools %s starting; data in %s", __version__, paths.data)
    window = webview.create_window(f"EntoTools {__version__}", app.launch_url, width=1280, height=860, min_size=(900, 600))
    dialogs.window = window
    window.events.closed += app.backups.flush
    try:
        webview.start(debug="--debug" in sys.argv)
    finally:
        app.stop()


if __name__ == "__main__":
    main()
