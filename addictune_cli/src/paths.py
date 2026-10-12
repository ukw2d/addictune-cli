"""Config, cache and log locations: one app name, OS conventions via platformdirs.

macOS: ~/Library/Application Support/addictune-cli, ~/Library/Caches/addictune-cli
Linux: ~/.config/addictune-cli, ~/.cache/addictune-cli
Windows: %LOCALAPPDATA%\\addictune-cli
"""

from pathlib import Path

from platformdirs import user_cache_path, user_config_path

APP_NAME = "addictune-cli"

CONFIG_DIR: Path = user_config_path(APP_NAME, appauthor=False)
CACHE_DIR: Path = user_cache_path(APP_NAME, appauthor=False)

SETTINGS_FILE = CONFIG_DIR / "settings.json"
SESSION_FILE = CONFIG_DIR / "session.json"
IMAGE_CACHE_DIR = CACHE_DIR / "images"
LOG_FILE = CACHE_DIR / "debug.log"
