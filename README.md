# EntoTools Desktop

Entotools.org, but downloadable to your desktop: growing degree day tools, specimen labels and a local collection database for Windows and macOS, with CSV backups and in-app updates.

**Status:** early development. See [PROJECT_LOG.md](PROJECT_LOG.md) for the plan, decisions and progress.

## Development

```bash
# Keep the virtual environment outside iCloud-synced folders (see PROJECT_LOG.md, F11)
/opt/homebrew/bin/python3.13 -m venv ~/.venvs/entotools-desktop
ln -sfn ~/.venvs/entotools-desktop .venv
.venv/bin/python -m pip install -e ".[dev]"

.venv/bin/python -m pytest -q                              # offline tests
ENTOTOOLS_NETWORK_TESTS=1 .venv/bin/python -m pytest -q    # + live checks against NOAA / Open-Meteo
.venv/bin/python -m entotools_desktop                      # run the app (--debug for logs + inspector)
```
