# EntoTools Desktop

Entotools.org, but downloadable to your desktop: growing degree day tools, specimen labels and a local collection database for Windows and macOS, with CSV backups and in-app updates.

**Status:** early development. See [PROJECT_LOG.md](PROJECT_LOG.md) for the plan, decisions and progress.

## Development

```bash
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m entotools_desktop
```
