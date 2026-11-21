"""Entry point: `python -m entotools_desktop` or the `entotools` script.

Phase 0 placeholder. Phase 1 adds the local API server; Phase 3 loads the
EntoTools pages from web/ into the window.
"""
from __future__ import annotations

import webview

from . import __version__


def main() -> None:
    webview.create_window(
        f"EntoTools {__version__}",
        html="<h1 style='font-family:sans-serif'>EntoTools desktop — under construction</h1>",
        width=1000,
        height=700,
    )
    webview.start()


if __name__ == "__main__":
    main()
