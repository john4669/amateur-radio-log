"""
config.py - Application settings stored as a JSON file alongside the app.
"""

import json
import os
import sys

# Config file lives in the same folder as the app (or the .exe when frozen)
if getattr(sys, "frozen", False):
    _CONFIG_DIR = os.path.dirname(sys.executable)
else:
    _CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "settings.json")

_DEFAULTS = {
    "db_path": "",  # Empty = use default (app folder)
    "theme": "system",  # system, light, dark, sky, sage, sand, lavender, rose
    "auto_backup": True,
    "max_backups": 5,
    "operator_callsign": "",
    "my_gridsquare": "",  # e.g. "EN91"
    "my_city": "",
    "my_state": "",   # e.g. "OH"
    "my_country": "",  # e.g. "United States"
    "default_power": "",
    "default_adif_export_path": "",
    "my_sig": "",  # e.g. "POTA"
    "my_sig_info": "",  # e.g. "US-1234"
    "flrig_host": "localhost",
    "flrig_port": 12345,
    "qrz_username": "",
    "qrz_password": "",
    "n3fjp_host": "",  # e.g. "192.168.1.100"
    "n3fjp_port": 1100,
}


def _load():
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults so new keys are always present
            merged = dict(_DEFAULTS)
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError):
            return dict(_DEFAULTS)
    return dict(_DEFAULTS)


def _save(settings):
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def get(key):
    return _load().get(key, _DEFAULTS.get(key))


def set(key, value):
    settings = _load()
    settings[key] = value
    _save(settings)


def get_db_path():
    """Return the effective database path."""
    custom = get("db_path")
    if custom and custom.strip():
        return custom.strip()
    # Default: same folder as the app
    return os.path.join(_CONFIG_DIR, "amateur_radio.db")
