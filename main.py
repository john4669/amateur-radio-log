"""
main.py - W0BCQ Logger
A cross-platform desktop app built with PySide6 (Qt6) and SQLite.
Stores QSOs locally and exports standard ADIF for N3FJP AC Log import.
"""

import sys
import os
import shutil
import socket
import json
import xmlrpc.client
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QPushButton,
    QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QTextEdit,
    QLabel, QMessageBox, QFileDialog, QToolBar, QStatusBar, QCheckBox,
    QDateEdit, QTimeEdit, QAbstractItemView, QGroupBox, QSpinBox,
    QScrollArea, QDialogButtonBox, QProgressBar,
)
from PySide6.QtCore import Qt, QDate, QTime, QSize, QTimer, Signal, QThread
from PySide6.QtGui import QAction, QActionGroup, QIcon, QColor, QPalette


from database import Database
import config
import adif
import fcc_db


APP_VERSION = "0.1.0"


# ── Band / Frequency / Mode Constants ─────────────────────────────

BANDS = [
    "", "160M", "80M", "60M", "40M", "30M", "20M", "17M", "15M",
    "12M", "10M", "6M", "2M", "1.25M", "70CM", "33CM", "23CM",
]

MODES = [
    "", "SSB", "CW", "FM", "AM", "FT8", "FT4", "RTTY", "PSK31",
    "JS8", "DSTAR", "DMR", "C4FM", "OLIVIA", "SSTV", "VARA",
]

# Band edges in MHz: (low, high, band_name)
BAND_FREQ_MAP = [
    (1.800, 2.000, "160M"),
    (3.500, 4.000, "80M"),
    (5.250, 5.450, "60M"),
    (7.000, 7.300, "40M"),
    (10.100, 10.150, "30M"),
    (14.000, 14.350, "20M"),
    (18.068, 18.168, "17M"),
    (21.000, 21.450, "15M"),
    (24.890, 24.990, "12M"),
    (28.000, 29.700, "10M"),
    (50.000, 54.000, "6M"),
    (144.000, 148.000, "2M"),
    (222.000, 225.000, "1.25M"),
    (420.000, 450.000, "70CM"),
    (902.000, 928.000, "33CM"),
    (1240.000, 1300.000, "23CM"),
]

BAND_DEFAULT_FREQ = {
    "160M": 1.900, "80M": 3.750, "60M": 5.357, "40M": 7.150,
    "30M": 10.125, "20M": 14.175, "17M": 18.118, "15M": 21.225,
    "12M": 24.940, "10M": 28.400, "6M": 50.125, "2M": 146.520,
    "1.25M": 223.500, "70CM": 446.000, "33CM": 927.500, "23CM": 1270.000,
}

PHONE_MODES = {"SSB", "FM", "AM", "DSTAR", "DMR", "C4FM"}
DIGITAL_SIGNAL_MODES = {"FT8", "FT4"}

# flrig returns raw rig mode names — map to our standard mode names
FLRIG_MODE_MAP = {
    "USB": "SSB", "LSB": "SSB", "USB-D": "SSB", "LSB-D": "SSB",
    "CW": "CW", "CW-R": "CW", "CWR": "CW",
    "FM": "FM", "NFM": "FM", "WFM": "FM",
    "AM": "AM",
    "RTTY": "RTTY", "RTTY-R": "RTTY", "RTTYR": "RTTY",
    "PSK": "PSK31",
    "FT8": "FT8", "FT4": "FT4",
    "DSTAR": "DSTAR", "D-STAR": "DSTAR",
    "DMR": "DMR",
    "C4FM": "C4FM",
}


def freq_to_band(freq_mhz):
    """Return the band name for a frequency, or '' if not in a known band."""
    for low, high, band in BAND_FREQ_MAP:
        if low <= freq_mhz <= high:
            return band
    return ""


def band_to_default_freq(band):
    """Return a default frequency for a band, or 0.0."""
    return BAND_DEFAULT_FREQ.get(band, 0.0)


def default_rst_for_mode(mode):
    """Return the default RST report for a given mode."""
    if mode in PHONE_MODES:
        return "59"
    if mode in DIGITAL_SIGNAL_MODES:
        return "-10"
    return "599"


# ── flrig Integration ─────────────────────────────────────────────

def fetch_flrig(host="localhost", port=12345):
    """Poll flrig for current frequency and mode.

    Returns:
        (freq_mhz, raw_mode, mapped_mode) on success, or None on failure.
    """
    import socket
    try:
        # Use a transport with a short timeout so the UI never hangs
        transport = xmlrpc.client.Transport()
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(1.0)
        try:
            proxy = xmlrpc.client.ServerProxy(
                f"http://{host}:{port}/",
                transport=transport,
                allow_none=True,
            )
            freq_hz = proxy.rig.get_vfo()
            raw_mode = proxy.rig.get_mode()
        finally:
            socket.setdefaulttimeout(old_timeout)

        freq_mhz = float(freq_hz) / 1_000_000.0
        raw_mode = str(raw_mode).strip()
        mapped_mode = FLRIG_MODE_MAP.get(raw_mode.upper(), raw_mode.upper())

        return freq_mhz, raw_mode, mapped_mode

    except Exception:
        return None


# ── QRZ Lookup ────────────────────────────────────────────────────

QRZ_URL = "https://xmldata.qrz.com/xml/current/"
QRZ_NS = {"q": "http://xmldata.qrz.com"}

# Module-level session cache
_qrz_session_key = None


def _qrz_find(root, path):
    """Find an element using the QRZ namespace."""
    return root.find(path, QRZ_NS)


def qrz_login(username, password):
    """Authenticate with QRZ and return a session key, or None on failure."""
    global _qrz_session_key
    try:
        params = urllib.parse.urlencode({
            "username": username,
            "password": password,
            "agent": f"W0BCQLogger{APP_VERSION}",
        })
        url = f"{QRZ_URL}?{params}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            root = ET.fromstring(resp.read())
        key_elem = _qrz_find(root, ".//q:Session/q:Key")
        if key_elem is not None and key_elem.text:
            _qrz_session_key = key_elem.text
            return _qrz_session_key
    except Exception:
        pass
    return None


def qrz_lookup(callsign, username=None, password=None):
    """Look up a callsign on QRZ. Returns a dict of fields or None.

    Reuses cached session key; re-authenticates if expired.
    """
    global _qrz_session_key

    if not _qrz_session_key:
        if username and password:
            qrz_login(username, password)
        if not _qrz_session_key:
            return None

    # Try lookup, re-auth once if session expired
    for attempt in range(2):
        try:
            params = urllib.parse.urlencode({
                "s": _qrz_session_key,
                "callsign": callsign,
            })
            url = f"{QRZ_URL}?{params}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                root = ET.fromstring(resp.read())

            cs_elem = _qrz_find(root, ".//q:Callsign")
            if cs_elem is not None:
                # Strip namespace prefix from tag names in returned dict
                ns_prefix = "{http://xmldata.qrz.com}"
                return {
                    elem.tag.replace(ns_prefix, ""): (elem.text or "").strip()
                    for elem in cs_elem
                }

            # Session may have expired — check for missing key
            key_elem = _qrz_find(root, ".//q:Session/q:Key")
            if key_elem is None or not key_elem.text:
                _qrz_session_key = None
                if attempt == 0 and username and password:
                    qrz_login(username, password)
                    continue
            return None

        except Exception:
            return None

    return None


# ── N3FJP AC Log Integration ──────────────────────────────────────

class N3FJPConnection:
    """Manages a TCP connection to N3FJP AC Log for sending multiple records."""

    def __init__(self, host, port=1100):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect((self.host, self.port))

    def send_command(self, cmd):
        """Send a command and return the response."""
        self.sock.sendall((cmd + "\r\n").encode("utf-8"))
        import time
        time.sleep(0.05)  # N3FJP requires at least 5ms between commands
        try:
            return self.sock.recv(4096).decode("utf-8", errors="replace").strip()
        except socket.timeout:
            return ""

    def send_adif_record(self, adif_record):
        """Send a single ADIF record string (without <eor>)."""
        adif_record = adif_record.strip()
        adif_record = adif_record.replace(" <eor>", "").replace("<eor>", "")
        cmd = f"<CMD><ADDADIFRECORD><VALUE>{adif_record}<EOR></VALUE></CMD>"
        return self.send_command(cmd)

    def close(self):
        if self.sock:
            try:
                self.sock.sendall(b"\r\n")
            except Exception:
                pass
            self.sock.close()
            self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()


def n3fjp_test_connection(host, port):
    """Test connection to N3FJP AC Log. Returns program info or None."""
    try:
        with N3FJPConnection(host, port) as conn:
            return conn.send_command("<CMD><PROGRAM></CMD>")
    except Exception:
        return None


# ── Resource Path ─────────────────────────────────────────────────

def _resource_path(filename):
    """Resolve path to a bundled resource file (works frozen and unfrozen)."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)


# ── Theme System ──────────────────────────────────────────────────

def _make_palette(colors):
    """Build a QPalette from a dict of role -> color hex values."""
    pal = QPalette()
    role_map = {
        "window":          QPalette.Window,
        "window_text":     QPalette.WindowText,
        "base":            QPalette.Base,
        "alt_base":        QPalette.AlternateBase,
        "text":            QPalette.Text,
        "button":          QPalette.Button,
        "button_text":     QPalette.ButtonText,
        "highlight":       QPalette.Highlight,
        "highlight_text":  QPalette.HighlightedText,
        "tooltip_base":    QPalette.ToolTipBase,
        "tooltip_text":    QPalette.ToolTipText,
        "bright_text":     QPalette.BrightText,
        "link":            QPalette.Link,
    }
    for key, role in role_map.items():
        if key in colors:
            pal.setColor(role, QColor(colors[key]))
    # Disabled text
    if "disabled_text" in colors:
        pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(colors["disabled_text"]))
        pal.setColor(QPalette.Disabled, QPalette.Text, QColor(colors["disabled_text"]))
        pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(colors["disabled_text"]))
    return pal


THEMES = {
    "system": None,
    "light": {
        "window": "#F7F7F7", "window_text": "#333333", "base": "#FFFFFF",
        "alt_base": "#F2F2F2", "text": "#333333", "button": "#EBEBEB",
        "button_text": "#333333", "highlight": "#88B8E0", "highlight_text": "#FFFFFF",
        "tooltip_base": "#FFFFF0", "tooltip_text": "#333333",
        "bright_text": "#D06050", "link": "#6699CC", "disabled_text": "#B0B0B0",
    },
    "dark": {
        "window": "#484C50", "window_text": "#E8E8E8", "base": "#52565A",
        "alt_base": "#5A5E62", "text": "#E8E8E8", "button": "#606468",
        "button_text": "#E8E8E8", "highlight": "#88B8E0", "highlight_text": "#FFFFFF",
        "tooltip_base": "#5A5E62", "tooltip_text": "#E8E8E8",
        "bright_text": "#F09080", "link": "#99C4E8", "disabled_text": "#909090",
    },
    "sky": {
        "window": "#E8F0F8", "window_text": "#3A4A5A", "base": "#F0F6FC",
        "alt_base": "#DCEAF5", "text": "#3A4A5A", "button": "#D0E2F0",
        "button_text": "#3A4A5A", "highlight": "#7AAED4", "highlight_text": "#FFFFFF",
        "tooltip_base": "#F0F6FC", "tooltip_text": "#3A4A5A",
        "bright_text": "#D06050", "link": "#5A90B8", "disabled_text": "#98AAB8",
    },
    "sage": {
        "window": "#EAF0E6", "window_text": "#3A4A3A", "base": "#F2F7F0",
        "alt_base": "#DEE8DA", "text": "#3A4A3A", "button": "#D2E0CC",
        "button_text": "#3A4A3A", "highlight": "#88B888", "highlight_text": "#FFFFFF",
        "tooltip_base": "#F2F7F0", "tooltip_text": "#3A4A3A",
        "bright_text": "#D06050", "link": "#608A60", "disabled_text": "#98A898",
    },
    "sand": {
        "window": "#F0EBE0", "window_text": "#4A4038", "base": "#F7F3EA",
        "alt_base": "#E8E0D4", "text": "#4A4038", "button": "#DED6C8",
        "button_text": "#4A4038", "highlight": "#C8A878", "highlight_text": "#FFFFFF",
        "tooltip_base": "#F7F3EA", "tooltip_text": "#4A4038",
        "bright_text": "#C06050", "link": "#A08050", "disabled_text": "#B0A898",
    },
    "lavender": {
        "window": "#EDE8F2", "window_text": "#403848", "base": "#F4F0F8",
        "alt_base": "#E2DCE8", "text": "#403848", "button": "#D8D0E0",
        "button_text": "#403848", "highlight": "#A088C0", "highlight_text": "#FFFFFF",
        "tooltip_base": "#F4F0F8", "tooltip_text": "#403848",
        "bright_text": "#D06050", "link": "#8870A8", "disabled_text": "#A098B0",
    },
    "rose": {
        "window": "#F2E8EA", "window_text": "#4A3838", "base": "#F8F0F2",
        "alt_base": "#E8DDE0", "text": "#4A3838", "button": "#E0D2D6",
        "button_text": "#4A3838", "highlight": "#C89098", "highlight_text": "#FFFFFF",
        "tooltip_base": "#F8F0F2", "tooltip_text": "#4A3838",
        "bright_text": "#C06050", "link": "#A87078", "disabled_text": "#B0A0A4",
    },
}


def apply_theme(app, theme_name):
    """Apply a color theme to the application."""
    if theme_name not in THEMES:
        theme_name = "system"
    colors = THEMES[theme_name]
    if colors is None:
        app.setPalette(app.style().standardPalette())
    else:
        app.setPalette(_make_palette(colors))


# ════════════════════════════════════════════════════════════════════
#  QSO Dialog
# ════════════════════════════════════════════════════════════════════

class QSODialog(QDialog):
    """Dialog for adding or editing a QSO contact."""

    def __init__(self, parent=None, qso=None, flrig_state=None, pota_mode=False,
                 pota_activation=None):
        """
        Args:
            parent: Parent widget.
            qso: Existing QSO record (sqlite3.Row or dict) for editing, or None for new.
            flrig_state: Tuple (freq_mhz, raw_mode, mapped_mode) or None.
            pota_mode: If True, pre-fill MY_SIG with "POTA" (kept for compatibility).
            pota_activation: Dict with my_sig/my_sig_info/my_city/my_state/my_country
                             overrides for this session, or None.
        """
        super().__init__(parent)
        self._qso = qso
        self._flrig_state = flrig_state
        self._pota_mode = pota_mode
        self._pota_activation = pota_activation
        self._suppress_auto = False
        self._previous_mode = ""

        self.setWindowTitle("Edit QSO" if qso else "Add QSO")
        self.setMinimumWidth(450)
        self._build_ui()

        if qso:
            self._populate(qso)
        else:
            self._apply_defaults()

    def _build_ui(self):
        layout = QFormLayout(self)

        # Call sign
        call_layout = QHBoxLayout()
        self.call_edit = QLineEdit()
        self.call_edit.setPlaceholderText("e.g. W1AW")
        self.call_edit.textChanged.connect(self._uppercase_call)
        self.call_edit.editingFinished.connect(self._lookup_callsign)
        call_layout.addWidget(self.call_edit)
        self._qrz_status = QLabel("")
        self._qrz_status.setStyleSheet("color: gray; font-size: 11px;")
        call_layout.addWidget(self._qrz_status)
        layout.addRow("Call Sign:", call_layout)

        # Date (UTC)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        layout.addRow("Date (UTC):", self.date_edit)

        # Time On (UTC)
        self.time_on_edit = QTimeEdit()
        self.time_on_edit.setDisplayFormat("HH:mm:ss")
        layout.addRow("Time On (UTC):", self.time_on_edit)

        # Time Off (UTC)
        self.time_off_edit = QTimeEdit()
        self.time_off_edit.setDisplayFormat("HH:mm:ss")
        self.time_off_edit.setSpecialValueText(" ")
        layout.addRow("Time Off (UTC):", self.time_off_edit)

        # Frequency
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(0.0, 99999.999)
        self.freq_spin.setDecimals(3)
        self.freq_spin.setSuffix(" MHz")
        self.freq_spin.setSpecialValueText(" ")
        self.freq_spin.valueChanged.connect(self._freq_changed)
        layout.addRow("Frequency:", self.freq_spin)

        # Band
        self.band_combo = QComboBox()
        self.band_combo.addItems(BANDS)
        self.band_combo.currentTextChanged.connect(self._band_changed)
        layout.addRow("Band:", self.band_combo)

        # Mode
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODES)
        self.mode_combo.currentTextChanged.connect(self._mode_changed)
        layout.addRow("Mode:", self.mode_combo)

        # RST Sent / Rcvd
        rst_layout = QHBoxLayout()
        self.rst_sent_edit = QLineEdit()
        self.rst_sent_edit.setPlaceholderText("59")
        self.rst_sent_edit.setMaximumWidth(80)
        rst_layout.addWidget(QLabel("Sent:"))
        rst_layout.addWidget(self.rst_sent_edit)
        self.rst_rcvd_edit = QLineEdit()
        self.rst_rcvd_edit.setPlaceholderText("59")
        self.rst_rcvd_edit.setMaximumWidth(80)
        rst_layout.addWidget(QLabel("  Rcvd:"))
        rst_layout.addWidget(self.rst_rcvd_edit)
        rst_layout.addStretch()
        layout.addRow("RST:", rst_layout)

        # TX Power
        self.power_edit = QLineEdit()
        self.power_edit.setPlaceholderText("e.g. 100")
        self.power_edit.setMaximumWidth(120)
        layout.addRow("TX Power:", self.power_edit)

        # Name
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Operator name")
        layout.addRow("Name:", self.name_edit)

        # QTH
        self.qth_edit = QLineEdit()
        self.qth_edit.setPlaceholderText("City, State")
        layout.addRow("QTH:", self.qth_edit)

        # State / Country row
        state_country = QHBoxLayout()
        self.state_edit = QLineEdit()
        self.state_edit.setPlaceholderText("e.g. OH")
        self.state_edit.setMaximumWidth(80)
        state_country.addWidget(QLabel("State:"))
        state_country.addWidget(self.state_edit)
        self.country_edit = QLineEdit()
        self.country_edit.setPlaceholderText("e.g. US")
        state_country.addWidget(QLabel("  Country:"))
        state_country.addWidget(self.country_edit)
        state_country.addStretch()
        layout.addRow("", state_country)

        # Grid Square
        self.grid_edit = QLineEdit()
        self.grid_edit.setPlaceholderText("e.g. FN42")
        self.grid_edit.setMaxLength(6)
        self.grid_edit.setMaximumWidth(120)
        layout.addRow("Grid Square:", self.grid_edit)

        # Their Sig / Sig Info (other station's activity, e.g. POTA activator being hunted)
        sig_layout = QHBoxLayout()
        self.sig_edit = QLineEdit()
        self.sig_edit.setPlaceholderText("e.g. POTA")
        self.sig_edit.setMaximumWidth(100)
        sig_layout.addWidget(self.sig_edit)
        self.sig_info_edit = QLineEdit()
        self.sig_info_edit.setPlaceholderText("e.g. US-1234")
        sig_layout.addWidget(self.sig_info_edit)
        layout.addRow("Their Sig / Info:", sig_layout)

        # My Sig / My Sig Info (your own activity, e.g. you are the activator)
        my_sig_layout = QHBoxLayout()
        self.my_sig_edit = QLineEdit()
        self.my_sig_edit.setPlaceholderText("e.g. POTA")
        self.my_sig_edit.setMaximumWidth(100)
        my_sig_layout.addWidget(self.my_sig_edit)
        self.my_sig_info_edit = QLineEdit()
        self.my_sig_info_edit.setPlaceholderText("e.g. US-1234")
        my_sig_layout.addWidget(self.my_sig_info_edit)
        layout.addRow("My Sig / Info:", my_sig_layout)

        # Operator
        self.operator_edit = QLineEdit()
        self.operator_edit.setPlaceholderText("Your callsign")
        self.operator_edit.textChanged.connect(
            lambda: self.operator_edit.setText(self.operator_edit.text().upper())
        )
        layout.addRow("Operator:", self.operator_edit)

        # My Grid Square
        self.my_grid_edit = QLineEdit()
        self.my_grid_edit.setPlaceholderText("e.g. EN91")
        self.my_grid_edit.setMaxLength(6)
        self.my_grid_edit.setMaximumWidth(120)
        self.my_grid_edit.textChanged.connect(
            lambda: self.my_grid_edit.setText(self.my_grid_edit.text().upper())
        )
        layout.addRow("My Grid:", self.my_grid_edit)

        # My City
        self.my_city_edit = QLineEdit()
        self.my_city_edit.setPlaceholderText("City")
        layout.addRow("My City:", self.my_city_edit)

        # My State / Country
        my_loc_layout = QHBoxLayout()
        self.my_state_edit = QLineEdit()
        self.my_state_edit.setPlaceholderText("e.g. OH")
        self.my_state_edit.setMaximumWidth(80)
        self.my_state_edit.textChanged.connect(
            lambda: self.my_state_edit.setText(self.my_state_edit.text().upper())
        )
        my_loc_layout.addWidget(QLabel("State:"))
        my_loc_layout.addWidget(self.my_state_edit)
        self.my_country_edit = QLineEdit()
        self.my_country_edit.setPlaceholderText("e.g. United States")
        my_loc_layout.addWidget(QLabel("  Country:"))
        my_loc_layout.addWidget(self.my_country_edit)
        my_loc_layout.addStretch()
        layout.addRow("", my_loc_layout)

        # Notes
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        self.notes_edit.setPlaceholderText("Notes / comments")
        layout.addRow("Notes:", self.notes_edit)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._validate_and_accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow("", btn_layout)

    def _apply_defaults(self):
        """Set defaults for a new QSO."""
        utc_now = datetime.now(timezone.utc)
        self.date_edit.setDate(QDate(utc_now.year, utc_now.month, utc_now.day))
        self.time_on_edit.setTime(QTime(utc_now.hour, utc_now.minute, utc_now.second))
        self.time_off_edit.setTime(QTime(0, 0, 0))  # Special value = empty

        # Apply flrig state if available
        if self._flrig_state:
            freq_mhz, raw_mode, mapped_mode = self._flrig_state
            self._suppress_auto = True
            self.freq_spin.setValue(freq_mhz)
            band = freq_to_band(freq_mhz)
            if band:
                idx = self.band_combo.findText(band)
                if idx >= 0:
                    self.band_combo.setCurrentIndex(idx)
            if mapped_mode:
                idx = self.mode_combo.findText(mapped_mode)
                if idx >= 0:
                    self.mode_combo.setCurrentIndex(idx)
            self._suppress_auto = False
            self.freq_spin.setStyleSheet("QDoubleSpinBox { border: 2px solid #66AA66; }")
            self.freq_spin.setToolTip(f"From flrig: {raw_mode} {freq_mhz:.3f} MHz")
        else:
            self.freq_spin.setStyleSheet("QDoubleSpinBox { border: 2px solid #CC9944; }")
            self.freq_spin.setToolTip("flrig not available")

        # Config defaults (pota_activation overrides home QTH fields when active)
        act = self._pota_activation or {}
        self.power_edit.setText(config.get("default_power") or "")
        self.my_sig_edit.setText(act.get("my_sig") or (config.get("my_sig") or ""))
        self.my_sig_info_edit.setText(act.get("my_sig_info") or (config.get("my_sig_info") or ""))
        self.operator_edit.setText(config.get("operator_callsign") or "")
        self.my_grid_edit.setText(act.get("my_gridsquare") or (config.get("my_gridsquare") or ""))
        self.my_city_edit.setText(act.get("my_city") or (config.get("my_city") or ""))
        self.my_state_edit.setText(act.get("my_state") or (config.get("my_state") or ""))
        self.my_country_edit.setText(act.get("my_country") or (config.get("my_country") or ""))

        # Set RST defaults based on current mode
        mode = self.mode_combo.currentText()
        if mode:
            rst = default_rst_for_mode(mode)
            self.rst_sent_edit.setText(rst)
            self.rst_rcvd_edit.setText(rst)
            self._previous_mode = mode

    def _populate(self, qso):
        """Fill fields from an existing QSO record."""
        self.call_edit.setText(qso["call"] or "")

        # Date: YYYYMMDD → QDate
        ds = qso["qso_date"] or ""
        if len(ds) == 8:
            self.date_edit.setDate(QDate(int(ds[:4]), int(ds[4:6]), int(ds[6:])))

        # Time On: HHMMSS → QTime
        ts = qso["time_on"] or ""
        if len(ts) >= 4:
            h, m = int(ts[:2]), int(ts[2:4])
            s = int(ts[4:6]) if len(ts) >= 6 else 0
            self.time_on_edit.setTime(QTime(h, m, s))

        # Time Off
        to = qso["time_off"] or ""
        if len(to) >= 4:
            h, m = int(to[:2]), int(to[2:4])
            s = int(to[4:6]) if len(to) >= 6 else 0
            self.time_off_edit.setTime(QTime(h, m, s))
        else:
            self.time_off_edit.setTime(QTime(0, 0, 0))

        self._suppress_auto = True
        self.freq_spin.setValue(qso["freq"] or 0.0)
        idx = self.band_combo.findText(qso["band"] or "")
        if idx >= 0:
            self.band_combo.setCurrentIndex(idx)
        idx = self.mode_combo.findText(qso["mode"] or "")
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self._suppress_auto = False

        self._previous_mode = qso["mode"] or ""
        self.rst_sent_edit.setText(qso["rst_sent"] or "")
        self.rst_rcvd_edit.setText(qso["rst_rcvd"] or "")
        self.power_edit.setText(qso["tx_pwr"] or "")
        self.name_edit.setText(qso["name"] or "")
        self.qth_edit.setText(qso["qth"] or "")
        self.state_edit.setText(qso["state"] or "")
        self.country_edit.setText(qso["country"] or "")
        self.grid_edit.setText(qso["gridsquare"] or "")
        self.sig_edit.setText(qso["sig"] or "")
        self.sig_info_edit.setText(qso["sig_info"] or "")
        self.my_sig_edit.setText(qso["my_sig"] or "")
        self.my_sig_info_edit.setText(qso["my_sig_info"] or "")
        self.operator_edit.setText(qso["operator"] or "")
        self.my_grid_edit.setText(qso["my_gridsquare"] or "")
        self.my_city_edit.setText(qso["my_city"] or "")
        self.my_state_edit.setText(qso["my_state"] or "")
        self.my_country_edit.setText(qso["my_country"] or "")
        self.notes_edit.setPlainText(qso["comment"] or "")

        # No flrig border on edit dialog
        self.freq_spin.setStyleSheet("")
        self.freq_spin.setToolTip("")

    def _uppercase_call(self):
        text = self.call_edit.text()
        upper = text.upper()
        if text != upper:
            pos = self.call_edit.cursorPosition()
            self.call_edit.setText(upper)
            self.call_edit.setCursorPosition(pos)

    def _lookup_callsign(self):
        """Look up call sign on QRZ when the field loses focus."""
        call = self.call_edit.text().strip().upper()
        if not call or len(call) < 3:
            return

        username = config.get("qrz_username") or ""
        password = config.get("qrz_password") or ""

        self._qrz_status.setText("Looking up...")
        self._qrz_status.setStyleSheet("color: gray; font-size: 11px;")
        QApplication.processEvents()

        result = None
        if username and password:
            result = qrz_lookup(call, username, password)
        if result:
            fname = result.get("fname", "")
            lname = result.get("name", "")
            full_name = f"{fname} {lname}".strip()
            if full_name and not self.name_edit.text().strip():
                self.name_edit.setText(full_name)

            city = result.get("addr2", "")
            state = result.get("state", "")
            qth = f"{city}, {state}".strip(", ") if city or state else ""
            if qth and not self.qth_edit.text().strip():
                self.qth_edit.setText(qth)
            if state and not self.state_edit.text().strip():
                self.state_edit.setText(state)

            country = result.get("country", "")
            if country and not self.country_edit.text().strip():
                self.country_edit.setText(country)

            grid = result.get("grid", "")
            if grid and not self.grid_edit.text().strip():
                self.grid_edit.setText(grid)

            self._qrz_status.setText(full_name or "Found")
            self._qrz_status.setStyleSheet("color: green; font-size: 11px;")
        else:
            # Fall back to local FCC database
            fcc = fcc_db.lookup(call)
            if fcc:
                full_name = f"{fcc.get('first_name', '')} {fcc.get('last_name', '')}".strip()
                if full_name and not self.name_edit.text().strip():
                    self.name_edit.setText(full_name)
                city  = fcc.get("city", "")
                state = fcc.get("state", "")
                qth   = f"{city}, {state}".strip(", ") if city or state else ""
                if qth and not self.qth_edit.text().strip():
                    self.qth_edit.setText(qth)
                if state and not self.state_edit.text().strip():
                    self.state_edit.setText(state)
                lic = fcc.get("license_class", "")
                status_text = full_name or "Found"
                if lic:
                    status_text += f" ({lic})"
                self._qrz_status.setText(f"{status_text} [FCC]")
                self._qrz_status.setStyleSheet("color: #5588CC; font-size: 11px;")
            else:
                self._qrz_status.setText("Not found")
                self._qrz_status.setStyleSheet("color: #CC9944; font-size: 11px;")

    def _freq_changed(self, value):
        if self._suppress_auto:
            return
        band = freq_to_band(value)
        self._suppress_auto = True
        if band:
            idx = self.band_combo.findText(band)
            if idx >= 0:
                self.band_combo.setCurrentIndex(idx)
        else:
            self.band_combo.setCurrentIndex(0)  # blank
        self._suppress_auto = False

    def _band_changed(self, band_text):
        if self._suppress_auto:
            return
        if not band_text:
            return
        # Only set default freq if current freq is 0 or outside this band
        current_freq = self.freq_spin.value()
        current_band = freq_to_band(current_freq)
        if current_freq == 0 or current_band != band_text:
            default_freq = band_to_default_freq(band_text)
            if default_freq > 0:
                self._suppress_auto = True
                self.freq_spin.setValue(default_freq)
                self._suppress_auto = False

    def _mode_changed(self, mode_text):
        if self._suppress_auto:
            return
        if not mode_text:
            return
        # Only update RST if it still holds the previous default
        old_rst = default_rst_for_mode(self._previous_mode) if self._previous_mode else ""
        new_rst = default_rst_for_mode(mode_text)
        if not self.rst_sent_edit.text() or self.rst_sent_edit.text() == old_rst:
            self.rst_sent_edit.setText(new_rst)
        if not self.rst_rcvd_edit.text() or self.rst_rcvd_edit.text() == old_rst:
            self.rst_rcvd_edit.setText(new_rst)
        self._previous_mode = mode_text

    def _validate_and_accept(self):
        call = self.call_edit.text().strip()
        if not call:
            QMessageBox.warning(self, "Validation", "Call sign is required.")
            self.call_edit.setFocus()
            return

        mode = self.mode_combo.currentText()
        if not mode:
            QMessageBox.warning(self, "Validation", "Mode is required.")
            self.mode_combo.setFocus()
            return

        freq = self.freq_spin.value()
        band = self.band_combo.currentText()
        if freq == 0 and not band:
            QMessageBox.warning(self, "Validation", "Frequency or band is required.")
            self.freq_spin.setFocus()
            return

        self.accept()

    def get_data(self):
        """Return a dict of all field values, ready for database insertion."""
        d = self.date_edit.date()
        qso_date = f"{d.year():04d}{d.month():02d}{d.day():02d}"

        t = self.time_on_edit.time()
        time_on = f"{t.hour():02d}{t.minute():02d}{t.second():02d}"

        t_off = self.time_off_edit.time()
        if t_off == QTime(0, 0, 0):
            time_off = ""
        else:
            time_off = f"{t_off.hour():02d}{t_off.minute():02d}{t_off.second():02d}"

        return {
            "call": self.call_edit.text().strip().upper(),
            "qso_date": qso_date,
            "time_on": time_on,
            "time_off": time_off,
            "freq": self.freq_spin.value(),
            "band": self.band_combo.currentText(),
            "mode": self.mode_combo.currentText(),
            "rst_sent": self.rst_sent_edit.text().strip(),
            "rst_rcvd": self.rst_rcvd_edit.text().strip(),
            "tx_pwr": self.power_edit.text().strip(),
            "name": self.name_edit.text().strip(),
            "qth": self.qth_edit.text().strip(),
            "state": self.state_edit.text().strip().upper(),
            "country": self.country_edit.text().strip(),
            "gridsquare": self.grid_edit.text().strip().upper(),
            "operator": self.operator_edit.text().strip().upper(),
            "my_gridsquare": self.my_grid_edit.text().strip().upper(),
            "my_city": self.my_city_edit.text().strip(),
            "my_state": self.my_state_edit.text().strip().upper(),
            "my_country": self.my_country_edit.text().strip(),
            "sig": self.sig_edit.text().strip().upper(),
            "sig_info": self.sig_info_edit.text().strip().upper(),
            "my_sig": self.my_sig_edit.text().strip().upper(),
            "my_sig_info": self.my_sig_info_edit.text().strip().upper(),
            "comment": self.notes_edit.toPlainText().strip(),
        }


# ════════════════════════════════════════════════════════════════════
#  POTA Spots Dialog
# ════════════════════════════════════════════════════════════════════

POTA_SPOTS_URL = "https://api.pota.app/spot/"
SSB_MODES = {"SSB", "USB", "LSB", "AM", "FM"}


class POTASpotsDialog(QDialog):
    """Live POTA SSB spots with one-click radio tuning via flrig."""

    _COLS = ["Activator", "Park", "Park Name", "Freq (MHz)", "Band", "Age", "Spotter", "Comment"]

    # Emitted when user clicks Add QSO; carries spot data dict for MainWindow to handle
    qso_requested = Signal(dict)

    def __init__(self, parent=None, flrig_host="localhost", flrig_port=12345):
        super().__init__(parent)
        self.setWindowTitle("POTA Spots (SSB)")
        self.setMinimumSize(950, 500)
        self.resize(1100, 560)
        self._flrig_host = flrig_host
        self._flrig_port = flrig_port
        self._all_spots = []
        self._build_ui()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._fetch_spots)
        self._refresh_timer.start(60_000)

        # Defer initial fetch until after the dialog is shown and fully laid out
        QTimer.singleShot(50, self._fetch_spots)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Band:"))
        self.band_combo = QComboBox()
        self.band_combo.setMinimumWidth(80)
        self.band_combo.addItem("All")
        # Use lambda so the string argument from the signal is discarded cleanly
        self.band_combo.currentIndexChanged.connect(self._band_changed)
        bar.addWidget(self.band_combo)
        bar.addStretch()
        self._status_label = QLabel("Loading…")
        bar.addWidget(self._status_label)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._fetch_spots)
        bar.addWidget(refresh_btn)
        layout.addLayout(bar)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Activator
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Park
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)           # Park Name
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Freq
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Band
        hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Age
        hdr.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Spotter
        hdr.setSectionResizeMode(7, QHeaderView.Stretch)           # Comment
        self.table.doubleClicked.connect(self._tune_radio)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        tune_btn = QPushButton("Tune Radio")
        tune_btn.clicked.connect(self._tune_radio)
        btn_row.addWidget(tune_btn)
        add_qso_btn = QPushButton("Add QSO")
        add_qso_btn.clicked.connect(self._request_add_qso)
        btn_row.addWidget(add_qso_btn)

        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _fetch_spots(self):
        self._status_label.setText("Loading…")
        QApplication.processEvents()
        try:
            req = urllib.request.Request(
                POTA_SPOTS_URL,
                headers={"User-Agent": f"W0BCQLogger/{APP_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            self._all_spots = [
                s for s in data
                if str(s.get("mode", "")).upper() in SSB_MODES
                and not s.get("invalid")
            ]

            # POTA API returns band as null — derive it from frequency
            for spot in self._all_spots:
                if not spot.get("band"):
                    try:
                        freq_mhz = float(spot.get("frequency") or 0) / 1000.0
                        spot["band"] = freq_to_band(freq_mhz) or ""
                    except (ValueError, TypeError):
                        spot["band"] = ""

            # Deduplicate: keep only the most recent spot per activator+park
            seen = {}
            for spot in sorted(self._all_spots, key=lambda s: s.get("spotTime", ""), reverse=True):
                key = (spot.get("activator", "").upper(), spot.get("reference", "").upper())
                if key not in seen:
                    seen[key] = spot
            self._all_spots = list(seen.values())

            bands = sorted(
                {s["band"].upper() for s in self._all_spots if s.get("band")},
                key=lambda b: (len(b), b),
            )
            self.band_combo.blockSignals(True)
            prev = self.band_combo.currentText()
            self.band_combo.clear()
            self.band_combo.addItem("All")
            self.band_combo.addItems(bands)
            idx = self.band_combo.findText(prev)
            self.band_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.band_combo.blockSignals(False)

            self._apply_filter()
        except Exception as e:
            self._status_label.setText(f"Error: {e}")

    def _band_changed(self, index):
        self._apply_filter()

    def _apply_filter(self):
        band = self.band_combo.currentText()
        spots = self._all_spots
        if band != "All":
            spots = [s for s in spots if (s.get("band") or "").upper() == band]

        now_utc = datetime.now(timezone.utc)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(spots))

        for row, spot in enumerate(spots):
            # POTA API frequency is in kHz (e.g. "14255" = 14.255 MHz)
            freq_str = spot.get("frequency", "")
            try:
                freq_khz = float(freq_str)
                freq_display = f"{freq_khz / 1000.0:.3f}"
            except (ValueError, TypeError):
                freq_khz = 0.0
                freq_display = freq_str

            # Spot age
            age_display = ""
            try:
                st = spot.get("spotTime", "").rstrip("Z")
                if st:
                    spot_dt = datetime.fromisoformat(st).replace(tzinfo=timezone.utc)
                    age_s = max(0, int((now_utc - spot_dt).total_seconds()))
                    if age_s < 3600:
                        age_display = f"{age_s // 60}m"
                    else:
                        age_display = f"{age_s // 3600}h{(age_s % 3600) // 60:02d}m"
            except Exception:
                pass

            values = [
                spot.get("activator", ""),
                spot.get("reference", ""),
                spot.get("name", ""),
                freq_display,
                (spot.get("band") or "").upper(),
                age_display,
                spot.get("spotter", ""),
                spot.get("comments", ""),
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                item.setData(Qt.UserRole, freq_khz)
                self.table.setItem(row, col, item)

        self.table.setSortingEnabled(True)
        self.table.resizeRowsToContents()
        self._status_label.setText(f"{len(spots)} spot(s)")

    def _tune_radio(self):
        row = self.table.currentRow()
        if row < 0:
            return
        freq_khz = self.table.item(row, 0).data(Qt.UserRole)
        if not freq_khz:
            return

        # flrig set_vfo / set_frequency require a float (double), not int
        freq_hz = float(freq_khz * 1000.0)
        freq_mhz = freq_khz / 1000.0
        rig_mode = "USB" if freq_mhz >= 10.0 else "LSB"

        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(2.0)
            proxy = xmlrpc.client.ServerProxy(
                f"http://{self._flrig_host}:{self._flrig_port}/",
                allow_none=True,
            )
            proxy.rig.set_frequency(freq_hz)
            proxy.rig.set_mode(rig_mode)
            activator = self.table.item(row, 0).text()
            park = self.table.item(row, 1).text()
            self._status_label.setText(
                f"Tuned: {freq_mhz:.3f} MHz {rig_mode} — {activator} {park}"
            )
        except Exception as e:
            QMessageBox.warning(self, "Tune Radio", f"Could not tune radio:\n{e}")
        finally:
            socket.setdefaulttimeout(old_timeout)

    def _request_add_qso(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Add QSO", "Select a spot first.")
            return
        freq_khz = self.table.item(row, 0).data(Qt.UserRole)
        self.qso_requested.emit({
            "call":     self.table.item(row, 0).text(),   # Activator
            "park_ref": self.table.item(row, 1).text(),   # Park reference
            "freq_mhz": freq_khz / 1000.0 if freq_khz else 0.0,
            "band":     self.table.item(row, 4).text(),   # Band col
            "mode":     "SSB",
        })



# ════════════════════════════════════════════════════════════════════
#  Settings Dialog
# ════════════════════════════════════════════════════════════════════

class SettingsDialog(QDialog):
    """Dialog for application settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(450)
        self._new_db_path = None
        self._should_copy = False
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # ── Operator Defaults ──
        op_group = QGroupBox("Operator Defaults")
        op_layout = QFormLayout()

        self.callsign_edit = QLineEdit(config.get("operator_callsign") or "")
        self.callsign_edit.setPlaceholderText("Your callsign")
        self.callsign_edit.textChanged.connect(
            lambda: self.callsign_edit.setText(self.callsign_edit.text().upper())
        )
        op_layout.addRow("Callsign:", self.callsign_edit)

        self.my_grid_edit = QLineEdit(config.get("my_gridsquare") or "")
        self.my_grid_edit.setPlaceholderText("e.g. EN91")
        self.my_grid_edit.setMaxLength(6)
        self.my_grid_edit.textChanged.connect(
            lambda: self.my_grid_edit.setText(self.my_grid_edit.text().upper())
        )
        op_layout.addRow("Grid Square:", self.my_grid_edit)

        self.settings_my_city_edit = QLineEdit(config.get("my_city") or "")
        self.settings_my_city_edit.setPlaceholderText("City")
        op_layout.addRow("My City:", self.settings_my_city_edit)

        my_loc_layout = QHBoxLayout()
        self.settings_my_state_edit = QLineEdit(config.get("my_state") or "")
        self.settings_my_state_edit.setPlaceholderText("e.g. OH")
        self.settings_my_state_edit.setMaximumWidth(80)
        self.settings_my_state_edit.textChanged.connect(
            lambda: self.settings_my_state_edit.setText(
                self.settings_my_state_edit.text().upper()
            )
        )
        my_loc_layout.addWidget(self.settings_my_state_edit)
        self.settings_my_country_edit = QLineEdit(config.get("my_country") or "")
        self.settings_my_country_edit.setPlaceholderText("e.g. United States")
        my_loc_layout.addWidget(self.settings_my_country_edit)
        op_layout.addRow("My State / Country:", my_loc_layout)

        self.power_edit = QLineEdit(config.get("default_power") or "")
        self.power_edit.setPlaceholderText("e.g. 100")
        op_layout.addRow("Default Power:", self.power_edit)

        self.my_sig_edit = QLineEdit(config.get("my_sig") or "")
        self.my_sig_edit.setPlaceholderText("e.g. POTA, SOTA")
        op_layout.addRow("My Sig:", self.my_sig_edit)

        self.my_sig_info_edit = QLineEdit(config.get("my_sig_info") or "")
        self.my_sig_info_edit.setPlaceholderText("e.g. US-1234")
        op_layout.addRow("My Sig Info:", self.my_sig_info_edit)

        op_group.setLayout(op_layout)
        layout.addWidget(op_group)

        # ── flrig Connection ──
        flrig_group = QGroupBox("flrig Connection")
        flrig_layout = QFormLayout()

        self.flrig_host_edit = QLineEdit(str(config.get("flrig_host") or "localhost"))
        flrig_layout.addRow("Host:", self.flrig_host_edit)

        self.flrig_port_spin = QSpinBox()
        self.flrig_port_spin.setRange(1, 65535)
        self.flrig_port_spin.setValue(config.get("flrig_port") or 12345)
        flrig_layout.addRow("Port:", self.flrig_port_spin)

        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._test_flrig)
        self.flrig_status_label = QLabel("")
        self.flrig_status_label.setStyleSheet("color: gray;")
        flrig_layout.addRow(test_btn, self.flrig_status_label)

        flrig_group.setLayout(flrig_layout)
        layout.addWidget(flrig_group)

        # ── QRZ Lookup ──
        qrz_group = QGroupBox("QRZ Callsign Lookup")
        qrz_layout = QFormLayout()

        self.qrz_user_edit = QLineEdit(config.get("qrz_username") or "")
        self.qrz_user_edit.setPlaceholderText("QRZ username")
        qrz_layout.addRow("Username:", self.qrz_user_edit)

        self.qrz_pass_edit = QLineEdit(config.get("qrz_password") or "")
        self.qrz_pass_edit.setPlaceholderText("QRZ password")
        self.qrz_pass_edit.setEchoMode(QLineEdit.Password)
        qrz_layout.addRow("Password:", self.qrz_pass_edit)

        qrz_info = QLabel("Requires QRZ XML Logbook Data subscription")
        qrz_info.setStyleSheet("color: gray;")
        qrz_layout.addRow(qrz_info)

        test_qrz_btn = QPushButton("Test Login")
        test_qrz_btn.clicked.connect(self._test_qrz)
        self.qrz_status_label = QLabel("")
        self.qrz_status_label.setStyleSheet("color: gray;")
        qrz_layout.addRow(test_qrz_btn, self.qrz_status_label)

        qrz_group.setLayout(qrz_layout)
        layout.addWidget(qrz_group)

        # ── N3FJP AC Log ──
        n3fjp_group = QGroupBox("N3FJP AC Log (LAN Transfer)")
        n3fjp_layout = QFormLayout()

        self.n3fjp_host_edit = QLineEdit(config.get("n3fjp_host") or "")
        self.n3fjp_host_edit.setPlaceholderText("e.g. 192.168.1.100")
        n3fjp_layout.addRow("Host / IP:", self.n3fjp_host_edit)

        self.n3fjp_port_spin = QSpinBox()
        self.n3fjp_port_spin.setRange(1, 65535)
        self.n3fjp_port_spin.setValue(config.get("n3fjp_port") or 1100)
        n3fjp_layout.addRow("Port:", self.n3fjp_port_spin)

        test_n3fjp_btn = QPushButton("Test Connection")
        test_n3fjp_btn.clicked.connect(self._test_n3fjp)
        self.n3fjp_status_label = QLabel("")
        self.n3fjp_status_label.setStyleSheet("color: gray;")
        n3fjp_layout.addRow(test_n3fjp_btn, self.n3fjp_status_label)

        n3fjp_group.setLayout(n3fjp_layout)
        layout.addWidget(n3fjp_group)

        # ── ADIF Export ──
        export_group = QGroupBox("ADIF Export")
        export_layout = QHBoxLayout()

        self.export_path_edit = QLineEdit(config.get("default_adif_export_path") or "")
        self.export_path_edit.setPlaceholderText("Default export folder")
        export_layout.addWidget(self.export_path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_export_path)
        export_layout.addWidget(browse_btn)

        export_group.setLayout(export_layout)
        layout.addWidget(export_group)

        # ── Database Location ──
        db_group = QGroupBox("Database Location")
        db_layout = QVBoxLayout()

        current_path = config.get_db_path()
        self.db_path_label = QLabel(current_path)
        self.db_path_label.setWordWrap(True)
        self.db_path_label.setStyleSheet("color: gray;")
        db_layout.addWidget(self.db_path_label)

        db_btn_layout = QHBoxLayout()
        db_browse_btn = QPushButton("Change Location...")
        db_browse_btn.clicked.connect(self._browse_db)
        db_btn_layout.addWidget(db_browse_btn)

        db_reset_btn = QPushButton("Reset to Default")
        db_reset_btn.clicked.connect(self._reset_db)
        db_btn_layout.addWidget(db_reset_btn)
        db_btn_layout.addStretch()
        db_layout.addLayout(db_btn_layout)

        self.copy_check = QCheckBox("Copy existing data to new location")
        self.copy_check.setChecked(True)
        self.copy_check.setVisible(False)
        db_layout.addWidget(self.copy_check)

        self.db_info_label = QLabel("")
        self.db_info_label.setStyleSheet("color: gray;")
        self.db_info_label.setWordWrap(True)
        db_layout.addWidget(self.db_info_label)

        db_group.setLayout(db_layout)
        layout.addWidget(db_group)

        # ── Auto-Backup ──
        backup_group = QGroupBox("Backup")
        backup_layout = QFormLayout()

        self.auto_backup_check = QCheckBox("Auto-backup on close")
        self.auto_backup_check.setChecked(config.get("auto_backup"))
        backup_layout.addRow(self.auto_backup_check)

        self.max_backups_spin = QSpinBox()
        self.max_backups_spin.setRange(1, 50)
        self.max_backups_spin.setValue(config.get("max_backups") or 5)
        backup_layout.addRow("Max backups:", self.max_backups_spin)

        backup_group.setLayout(backup_layout)
        layout.addWidget(backup_group)

        # ── Buttons ──
        # Fixed Save/Cancel outside the scroll area
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save_and_accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        outer.addLayout(btn_layout)

    def _test_flrig(self):
        host = self.flrig_host_edit.text().strip() or "localhost"
        port = self.flrig_port_spin.value()
        result = fetch_flrig(host, port)
        if result:
            freq, raw_mode, mapped = result
            self.flrig_status_label.setText(
                f"Connected: {freq:.3f} MHz, {raw_mode}"
            )
            self.flrig_status_label.setStyleSheet("color: green;")
        else:
            self.flrig_status_label.setText("Could not connect to flrig")
            self.flrig_status_label.setStyleSheet("color: #CC6600;")

    def _test_qrz(self):
        user = self.qrz_user_edit.text().strip()
        pw = self.qrz_pass_edit.text().strip()
        if not user or not pw:
            self.qrz_status_label.setText("Enter username and password")
            self.qrz_status_label.setStyleSheet("color: #CC6600;")
            return
        key = qrz_login(user, pw)
        if key:
            self.qrz_status_label.setText("Login successful")
            self.qrz_status_label.setStyleSheet("color: green;")
        else:
            self.qrz_status_label.setText("Login failed — check credentials")
            self.qrz_status_label.setStyleSheet("color: #CC6600;")

    def _test_n3fjp(self):
        host = self.n3fjp_host_edit.text().strip()
        port = self.n3fjp_port_spin.value()
        if not host:
            self.n3fjp_status_label.setText("Enter host IP address")
            self.n3fjp_status_label.setStyleSheet("color: #CC6600;")
            return
        resp = n3fjp_test_connection(host, port)
        if resp:
            self.n3fjp_status_label.setText(f"Connected")
            self.n3fjp_status_label.setStyleSheet("color: green;")
        else:
            self.n3fjp_status_label.setText("Could not connect")
            self.n3fjp_status_label.setStyleSheet("color: #CC6600;")


    def _browse_export_path(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Default Export Folder",
            self.export_path_edit.text() or os.path.expanduser("~"),
        )
        if path:
            self.export_path_edit.setText(path)

    def _browse_db(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Select Database Location",
            os.path.expanduser("~"),
            "SQLite Database (*.db)",
        )
        if path:
            self._new_db_path = path
            self.db_path_label.setText(path)
            self.copy_check.setVisible(True)
            if os.path.exists(path):
                self.db_info_label.setText("Warning: File already exists and will be overwritten.")
                self.db_info_label.setStyleSheet("color: #CC6600;")
            else:
                self.db_info_label.setText("A new database will be created at this location.")
                self.db_info_label.setStyleSheet("color: gray;")

    def _reset_db(self):
        self._new_db_path = ""
        self.db_path_label.setText(config.get_db_path())
        self.copy_check.setVisible(False)
        self.db_info_label.setText("Will use default location.")
        self.db_info_label.setStyleSheet("color: gray;")

    def get_new_db_path(self):
        return self._new_db_path

    def should_copy(self):
        return self.copy_check.isChecked()

    def _save_and_accept(self):
        config.set("operator_callsign", self.callsign_edit.text().strip().upper())
        config.set("my_gridsquare", self.my_grid_edit.text().strip().upper())
        config.set("my_city", self.settings_my_city_edit.text().strip())
        config.set("my_state", self.settings_my_state_edit.text().strip().upper())
        config.set("my_country", self.settings_my_country_edit.text().strip())
        config.set("default_power", self.power_edit.text().strip())
        config.set("my_sig", self.my_sig_edit.text().strip().upper())
        config.set("my_sig_info", self.my_sig_info_edit.text().strip().upper())
        config.set("flrig_host", self.flrig_host_edit.text().strip() or "localhost")
        config.set("flrig_port", self.flrig_port_spin.value())
        config.set("qrz_username", self.qrz_user_edit.text().strip())
        config.set("qrz_password", self.qrz_pass_edit.text().strip())
        config.set("n3fjp_host", self.n3fjp_host_edit.text().strip())
        config.set("n3fjp_port", self.n3fjp_port_spin.value())
        config.set("default_adif_export_path", self.export_path_edit.text().strip())
        config.set("auto_backup", self.auto_backup_check.isChecked())
        config.set("max_backups", self.max_backups_spin.value())

        if self._new_db_path is not None:
            config.set("db_path", self._new_db_path)
            self._should_copy = self.copy_check.isChecked()

        self.accept()


# ════════════════════════════════════════════════════════════════════
#  POTA Activation Dialog
# ════════════════════════════════════════════════════════════════════

class POTAActivationDialog(QDialog):
    """Prompt for park info when starting a POTA activation session."""

    def __init__(self, parent=None, current=None):
        super().__init__(parent)
        self.setWindowTitle("POTA Activation")
        self.setMinimumWidth(360)

        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.park_edit = QLineEdit()
        self.park_edit.setPlaceholderText("e.g. US-1234")
        current_park = (current or {}).get("my_sig_info", "")
        self.park_edit.setText(current_park)
        layout.addRow("Park Reference *:", self.park_edit)

        self.city_edit = QLineEdit()
        self.city_edit.setPlaceholderText(config.get("my_city") or "City")
        self.city_edit.setText((current or {}).get("my_city", ""))
        layout.addRow("City:", self.city_edit)

        my_loc_layout = QHBoxLayout()
        self.state_edit = QLineEdit()
        self.state_edit.setPlaceholderText(config.get("my_state") or "e.g. OH")
        self.state_edit.setMaximumWidth(80)
        self.state_edit.setText((current or {}).get("my_state", ""))
        self.state_edit.textChanged.connect(
            lambda: self.state_edit.setText(self.state_edit.text().upper())
        )
        my_loc_layout.addWidget(self.state_edit)
        self.country_edit = QLineEdit()
        self.country_edit.setPlaceholderText(config.get("my_country") or "e.g. United States")
        self.country_edit.setText((current or {}).get("my_country", ""))
        my_loc_layout.addWidget(self.country_edit)
        layout.addRow("State / Country:", my_loc_layout)

        self.grid_edit = QLineEdit()
        self.grid_edit.setPlaceholderText(config.get("my_gridsquare") or "e.g. EN91")
        self.grid_edit.setMaximumWidth(120)
        self.grid_edit.setText((current or {}).get("my_gridsquare", ""))
        self.grid_edit.textChanged.connect(
            lambda: self.grid_edit.setText(self.grid_edit.text().upper())
        )
        layout.addRow("Grid Square:", self.grid_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

        self.park_edit.setFocus()

    def _accept(self):
        if not self.park_edit.text().strip():
            QMessageBox.warning(self, "Required", "Park Reference is required.")
            return
        self.accept()

    def get_data(self):
        return {
            "my_sig": "POTA",
            "my_sig_info": self.park_edit.text().strip().upper(),
            "my_city": self.city_edit.text().strip(),
            "my_state": self.state_edit.text().strip().upper(),
            "my_country": self.country_edit.text().strip(),
            "my_gridsquare": self.grid_edit.text().strip().upper(),
        }


# ════════════════════════════════════════════════════════════════════
#  FCC Database Import
# ════════════════════════════════════════════════════════════════════

class FCCImportWorker(QThread):
    progress = Signal(int, str)   # percent, message
    finished = Signal(bool, str)  # success, message

    def __init__(self):
        super().__init__()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            count = fcc_db.download_and_import(
                progress_cb=lambda pct, msg: self.progress.emit(pct, msg),
                cancelled_fn=lambda: self._cancelled,
            )
            self.finished.emit(True, f"Import complete — {count:,} callsigns.")
        except InterruptedError:
            self.finished.emit(False, "Cancelled.")
        except Exception as e:
            self.finished.emit(False, f"Error: {e}")


class FCCDatabaseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FCC Amateur Database")
        self.setMinimumWidth(440)
        self.setModal(True)
        self._worker = None

        layout = QVBoxLayout(self)

        last = fcc_db.get_last_updated()
        if last:
            age = (datetime.now(timezone.utc) - last).days
            info_text = f"Last updated: {last.strftime('%Y-%m-%d')} ({age} day{'s' if age != 1 else ''} ago)"
        else:
            info_text = "No FCC database installed."
        self._info_label = QLabel(info_text)
        layout.addWidget(self._info_label)

        self._status_label = QLabel(
            "Downloads the FCC ULS complete amateur license database (~18 MB).\n"
            "Provides offline callsign lookup when QRZ is unavailable."
        )
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        btn_layout = QHBoxLayout()
        self._download_btn = QPushButton("Download && Import")
        self._download_btn.clicked.connect(self._start)
        btn_layout.addWidget(self._download_btn)
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self._cancel_or_close)
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

    def _start(self):
        self._download_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._status_label.setText("Starting…")
        self._close_btn.setText("Cancel")

        self._worker = FCCImportWorker()
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, pct, msg):
        self._progress_bar.setValue(pct)
        self._status_label.setText(msg)

    def _on_finished(self, success, msg):
        self._progress_bar.setValue(100 if success else self._progress_bar.value())
        self._status_label.setText(msg)
        self._close_btn.setText("Close")
        self._download_btn.setEnabled(True)
        self._worker = None
        if success:
            last = fcc_db.get_last_updated()
            if last:
                self._info_label.setText(
                    f"Last updated: {last.strftime('%Y-%m-%d')} (just now)"
                )

    def _cancel_or_close(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        self.accept()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        event.accept()


# ════════════════════════════════════════════════════════════════════
#  Main Window
# ════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db

        # POTA activation (in-memory, resets on restart)
        self._pota_mode = False
        self._pota_activation = None  # dict with my_sig/my_sig_info/my_city/my_state/my_country
        # flrig polling state
        self._flrig_connected = False
        self._flrig_freq = 0.0
        self._flrig_mode = ""
        self._flrig_raw_mode = ""
        self._flrig_fail_count = 0

        self.setWindowTitle(f"W0BCQ Logger v{APP_VERSION}")
        self.setMinimumSize(1000, 600)
        self.resize(1200, 700)

        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._refresh_table()

        # Start flrig polling
        self._flrig_timer = QTimer(self)
        self._flrig_timer.timeout.connect(self._poll_flrig)
        self._flrig_timer.start(2000)
        # Initial poll immediately
        self._poll_flrig()

    # ── flrig Polling ──────────────────────────────────────────────

    def _poll_flrig(self):
        # Back off after repeated failures (try every 5th cycle = 10 seconds)
        if self._flrig_fail_count > 3:
            self._flrig_fail_count += 1
            if self._flrig_fail_count % 5 != 0:
                return
            # Reset after a while to keep retrying
            if self._flrig_fail_count > 50:
                self._flrig_fail_count = 4

        host = config.get("flrig_host") or "localhost"
        port = config.get("flrig_port") or 12345
        result = fetch_flrig(host, port)

        if result:
            self._flrig_freq, self._flrig_raw_mode, self._flrig_mode = result
            self._flrig_connected = True
            self._flrig_fail_count = 0
            self._radio_label.setText(
                f"  Radio: {self._flrig_freq:.3f} MHz  {self._flrig_raw_mode}"
            )
            self._radio_label.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: #228B22; padding: 2px 8px;"
            )
        else:
            self._flrig_connected = False
            self._flrig_fail_count += 1
            self._radio_label.setText("  Radio: not connected")
            self._radio_label.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: #CC9944; padding: 2px 8px;"
            )

    def _get_flrig_state(self):
        """Return the current flrig state tuple, or None if not connected."""
        if self._flrig_connected and self._flrig_freq > 0:
            return (self._flrig_freq, self._flrig_raw_mode, self._flrig_mode)
        return None

    # ── Menu Bar ───────────────────────────────────────────────────

    def _build_menu(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        export_action = QAction("Export &Selected to ADIF...", self)
        export_action.triggered.connect(self._export_selected_adif)
        file_menu.addAction(export_action)

        export_all_action = QAction("Export &All to ADIF...", self)
        export_all_action.setShortcut("Ctrl+E")
        export_all_action.triggered.connect(self._export_adif)
        file_menu.addAction(export_all_action)

        import_action = QAction("&Import from ADIF...", self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self._import_adif)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        fcc_action = QAction("Update &FCC Database...", self)
        fcc_action.triggered.connect(self._open_fcc_dialog)
        file_menu.addAction(fcc_action)

        file_menu.addSeparator()

        new_db_action = QAction("&New Database...", self)
        new_db_action.triggered.connect(self._new_database)
        file_menu.addAction(new_db_action)

        file_menu.addSeparator()

        send_sel_action = QAction("Send &Selected to AC Log...", self)
        send_sel_action.triggered.connect(self._send_selected_to_n3fjp)
        file_menu.addAction(send_sel_action)

        send_all_action = QAction("Send &All to AC Log...", self)
        send_all_action.triggered.connect(self._send_all_to_n3fjp)
        file_menu.addAction(send_all_action)

        file_menu.addSeparator()

        settings_action = QAction("&Settings...", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # QSO menu
        qso_menu = menubar.addMenu("&QSO")

        add_q = QAction("&Add QSO...", self)
        add_q.setShortcut("Ctrl+N")
        add_q.triggered.connect(self._add_qso)
        qso_menu.addAction(add_q)

        edit_q = QAction("&Edit QSO...", self)
        edit_q.triggered.connect(self._edit_qso)
        qso_menu.addAction(edit_q)

        del_q = QAction("&Delete QSO", self)
        del_q.setShortcut("Delete")
        del_q.triggered.connect(self._delete_qso)
        qso_menu.addAction(del_q)

        qso_menu.addSeparator()

        dup_q = QAction("D&uplicate QSO...", self)
        dup_q.setShortcut("Ctrl+D")
        dup_q.triggered.connect(self._duplicate_qso)
        qso_menu.addAction(dup_q)

        # View menu
        view_menu = menubar.addMenu("V&iew")
        theme_menu = view_menu.addMenu("&Theme")

        current_theme = config.get("theme") or "system"
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)

        theme_labels = {
            "system": "System Default",
            "light": "Light",
            "dark": "Dark",
            "sky": "Sky Blue",
            "sage": "Sage Green",
            "sand": "Warm Sand",
            "lavender": "Lavender",
            "rose": "Soft Rose",
        }
        for key, label in theme_labels.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(key == current_theme)
            action.setData(key)
            action.triggered.connect(self._change_theme)
            theme_group.addAction(action)
            theme_menu.addAction(action)

        # About menu
        about_menu = menubar.addMenu("&About")
        about_action = QAction("&About W0BCQ Logger", self)
        about_action.triggered.connect(self._show_about)
        about_menu.addAction(about_action)

    def _show_about(self):
        QMessageBox.about(
            self,
            "About W0BCQ Logger",
            f"<h3>W0BCQ Logger</h3>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p>A desktop app for logging amateur radio contacts on Linux and Windows. "
            f"Stores QSOs in SQLite and exports standard ADIF files for "
            f"import into N3FJP Amateur Contact Log and other software.</p>"
            f"<p>Features flrig integration for live frequency/mode, QRZ callsign lookup "
            f"with offline FCC database fallback, POTA activation support, "
            f"and direct transfer to N3FJP AC Log over LAN.</p>"
            f"<p>Built with PySide6 (Qt6).</p>"
            f"<hr>"
            f"<p>Copyright &copy; 2026 John Friede (W0BCQ)<br>"
            f"Licensed under CC BY-NC-SA 4.0</p>"
        )

    # ── Toolbar ────────────────────────────────────────────────────

    def _build_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        add_btn = QPushButton(" Add QSO")
        add_btn.clicked.connect(self._add_qso)
        toolbar.addWidget(add_btn)

        edit_btn = QPushButton(" Edit QSO")
        edit_btn.clicked.connect(self._edit_qso)
        toolbar.addWidget(edit_btn)

        del_btn = QPushButton(" Delete QSO")
        del_btn.clicked.connect(self._delete_qso)
        toolbar.addWidget(del_btn)

        dup_btn = QPushButton(" Duplicate QSO")
        dup_btn.clicked.connect(self._duplicate_qso)
        toolbar.addWidget(dup_btn)

        toolbar.addSeparator()

        export_sel_btn = QPushButton(" Export Selected")
        export_sel_btn.clicked.connect(self._export_selected_adif)
        toolbar.addWidget(export_sel_btn)

        export_all_btn = QPushButton(" Export All")
        export_all_btn.clicked.connect(self._export_adif)
        toolbar.addWidget(export_all_btn)

        toolbar.addSeparator()

        send_btn = QPushButton(" Send to AC Log")
        send_btn.clicked.connect(self._send_selected_to_n3fjp)
        toolbar.addWidget(send_btn)

        # ── POTA toolbar (second row) ──
        self.addToolBarBreak()
        pota_toolbar = QToolBar("POTA Toolbar")
        pota_toolbar.setMovable(False)
        pota_toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(pota_toolbar)

        self._pota_mode_btn = QPushButton("POTA Activation")
        self._pota_mode_btn.setCheckable(True)
        self._pota_mode_btn.setToolTip("Start a POTA activation session — sets MY_SIG and home QTH for this session")
        self._pota_mode_btn.clicked.connect(self._toggle_pota_mode)
        pota_toolbar.addWidget(self._pota_mode_btn)

        pota_spots_btn = QPushButton("POTA Spots")
        pota_spots_btn.setToolTip("Show live SSB POTA spots and tune radio")
        pota_spots_btn.clicked.connect(self._open_pota_spots)
        pota_toolbar.addWidget(pota_spots_btn)


    # ── Central Widget ─────────────────────────────────────────────

    def _build_central(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        # Summary bar
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet(
            "QLabel { background-color: palette(alternate-base); "
            "padding: 8px; border-radius: 4px; }"
        )
        layout.addWidget(self.summary_label)

        # Table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit_qso)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)

        columns = [
            "#", "Sent", "Date", "Time (UTC)", "Call Sign", "Freq (MHz)",
            "Band", "Mode", "RST Sent", "RST Rcvd",
            "Name", "QTH", "Notes",
        ]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # #
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Sent
        header.setSectionResizeMode(4, QHeaderView.Stretch)   # Call Sign
        header.setSectionResizeMode(12, QHeaderView.Stretch)  # Notes

        layout.addWidget(self.table)

    # ── Status Bar ─────────────────────────────────────────────────

    def _build_statusbar(self):
        sb = self.statusBar()
        sb.showMessage(f"Database: {self.db.db_path}")

        # UTC clock
        self._clock_label = QLabel("")
        self._clock_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 2px 8px;")
        sb.addPermanentWidget(self._clock_label)

        # Radio status label — large and bold
        self._radio_label = QLabel("  Radio: checking...")
        self._radio_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: gray; padding: 2px 8px;"
        )
        sb.addPermanentWidget(self._radio_label)

        # Clock timer — update every second
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

    def _update_clock(self):
        utc_now = datetime.now(timezone.utc)
        self._clock_label.setText(utc_now.strftime("%H:%M:%S UTC"))

    # ── Table Operations ───────────────────────────────────────────

    def _refresh_table(self):
        records = self.db.get_qsos()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(records))

        for row_idx, r in enumerate(records):
            # Row number
            num_item = QTableWidgetItem()
            num_item.setData(Qt.DisplayRole, row_idx + 1)
            num_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 0, num_item)

            # Sent indicator
            sent = bool(r["sent_to_aclog"])
            sent_item = QTableWidgetItem("Y" if sent else "")
            sent_item.setTextAlignment(Qt.AlignCenter)
            if sent:
                sent_item.setForeground(QColor("#228B22"))
            self.table.setItem(row_idx, 1, sent_item)

            # Date: YYYYMMDD → YYYY-MM-DD for display
            ds = r["qso_date"] or ""
            display_date = ds
            if len(ds) == 8:
                display_date = f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"
            date_item = QTableWidgetItem(display_date)
            date_item.setData(Qt.UserRole, r["id"])  # Store record ID
            self.table.setItem(row_idx, 2, date_item)

            # Time: HHMMSS → HH:MM:SS for display
            ts = r["time_on"] or ""
            display_time = ts
            if len(ts) == 6:
                display_time = f"{ts[:2]}:{ts[2:4]}:{ts[4:]}"
            elif len(ts) == 4:
                display_time = f"{ts[:2]}:{ts[2:]}"
            self.table.setItem(row_idx, 3, QTableWidgetItem(display_time))

            # Call sign
            self.table.setItem(row_idx, 4, QTableWidgetItem(r["call"] or ""))

            # Frequency
            freq = r["freq"] or 0.0
            freq_item = QTableWidgetItem(f"{freq:.3f}" if freq > 0 else "")
            freq_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            freq_item.setData(Qt.UserRole + 1, freq)  # For numeric sorting
            self.table.setItem(row_idx, 5, freq_item)

            # Band
            self.table.setItem(row_idx, 6, QTableWidgetItem(r["band"] or ""))

            # Mode
            self.table.setItem(row_idx, 7, QTableWidgetItem(r["mode"] or ""))

            # RST
            self.table.setItem(row_idx, 8, QTableWidgetItem(r["rst_sent"] or ""))
            self.table.setItem(row_idx, 9, QTableWidgetItem(r["rst_rcvd"] or ""))

            # Name
            self.table.setItem(row_idx, 10, QTableWidgetItem(r["name"] or ""))

            # QTH
            self.table.setItem(row_idx, 11, QTableWidgetItem(r["qth"] or ""))

            # Notes
            self.table.setItem(row_idx, 12, QTableWidgetItem(r["comment"] or ""))

        self.table.setSortingEnabled(True)
        self.table.resizeRowsToContents()
        self._refresh_summary()

    def _refresh_summary(self):
        s = self.db.get_summary()
        parts = [f"QSOs: {s['count']}"]

        if s["count"] > 0:
            # Date range
            first = s.get("first_date") or ""
            last = s.get("last_date") or ""
            if first and last:
                if len(first) == 8:
                    first = f"{first[:4]}-{first[4:6]}-{first[6:]}"
                if len(last) == 8:
                    last = f"{last[:4]}-{last[4:6]}-{last[6:]}"
                if first == last:
                    parts.append(f"Date: {first}")
                else:
                    parts.append(f"Dates: {first} to {last}")

            # Top modes
            if s.get("top_modes"):
                mode_str = ", ".join(f"{m} ({c})" for m, c in s["top_modes"])
                parts.append(f"Modes: {mode_str}")

            # Unique calls
            if s.get("unique_calls"):
                parts.append(f"Unique calls: {s['unique_calls']}")

        self.summary_label.setText("   |   ".join(parts))

    def _get_selected_qso_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 2)  # Date column stores ID
        if item is None:
            return None
        return item.data(Qt.UserRole)

    # ── QSO CRUD ───────────────────────────────────────────────────

    def _add_qso(self):
        dlg = QSODialog(self, flrig_state=self._get_flrig_state(), pota_mode=self._pota_mode,
                        pota_activation=self._pota_activation)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            self.db.add_qso(**data)
            self._refresh_table()
            self.statusBar().showMessage("QSO added.", 3000)

    def _edit_qso(self):
        qso_id = self._get_selected_qso_id()
        if qso_id is None:
            return
        qso = self.db.get_qso(qso_id)
        if not qso:
            return
        dlg = QSODialog(self, qso=qso)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            self.db.update_qso(qso_id, **data)
            self._refresh_table()
            self.statusBar().showMessage("QSO updated.", 3000)

    def _delete_qso(self):
        qso_id = self._get_selected_qso_id()
        if qso_id is None:
            return
        qso = self.db.get_qso(qso_id)
        if not qso:
            return
        reply = QMessageBox.question(
            self, "Delete QSO",
            f"Delete QSO with {qso['call']} on "
            f"{qso['qso_date']} at {qso['time_on']} UTC?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.db.delete_qso(qso_id)
            self._refresh_table()
            self.statusBar().showMessage("QSO deleted.", 3000)

    def _duplicate_qso(self):
        qso_id = self._get_selected_qso_id()
        if qso_id is None:
            return
        qso = self.db.get_qso(qso_id)
        if not qso:
            return

        # Open dialog pre-populated from the selected QSO
        dlg = QSODialog(self, qso=qso, flrig_state=self._get_flrig_state(), pota_mode=self._pota_mode,
                        pota_activation=self._pota_activation)
        # Override date/time to current UTC
        utc_now = datetime.now(timezone.utc)
        dlg.date_edit.setDate(QDate(utc_now.year, utc_now.month, utc_now.day))
        dlg.time_on_edit.setTime(QTime(utc_now.hour, utc_now.minute, utc_now.second))
        dlg.time_off_edit.setTime(QTime(0, 0, 0))
        # Clear call sign for new contact
        dlg.call_edit.clear()
        dlg.call_edit.setFocus()

        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            self.db.add_qso(**data)
            self._refresh_table()
            self.statusBar().showMessage("QSO added (duplicated).", 3000)

    # ── Export / Import ────────────────────────────────────────────

    def _export_selected_adif(self):
        ids = self._get_selected_qso_ids()
        if not ids:
            QMessageBox.information(
                self, "Export Selected",
                "No QSOs selected.\n\nSelect rows first (Ctrl+click or Shift+click),\n"
                "or use 'Export All to ADIF' to export everything.",
            )
            return
        qsos = [self.db.get_qso(qso_id) for qso_id in ids]
        qsos = [q for q in qsos if q]

        default_dir = config.get("default_adif_export_path") or os.path.expanduser("~")
        default_name = datetime.now().strftime("amateur_radio_selected_%Y%m%d.adi")
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export Selected QSOs to ADIF",
            os.path.join(default_dir, default_name),
            "ADIF Files (*.adi);;All Files (*)",
        )
        if not filepath:
            return

        count = adif.write_adif(filepath, qsos)
        self.statusBar().showMessage(f"Exported {count} QSO(s) to {filepath}", 5000)

    def _export_adif(self):
        default_dir = config.get("default_adif_export_path") or os.path.expanduser("~")
        default_name = datetime.now().strftime("amateur_radio_log_%Y%m%d.adi")
        default_path = os.path.join(default_dir, default_name)

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export ADIF",
            default_path,
            "ADIF Files (*.adi);;All Files (*)",
        )
        if not filepath:
            return

        qsos = self.db.get_all_qsos_for_export()
        count = adif.write_adif(filepath, qsos)
        self.statusBar().showMessage(f"Exported {count} QSOs to {filepath}", 5000)

    def _import_adif(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Import ADIF",
            os.path.expanduser("~"),
            "ADIF Files (*.adi *.adif);;All Files (*)",
        )
        if not filepath:
            return

        try:
            records = adif.read_adif(filepath)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to read ADIF file:\n{e}")
            return

        if not records:
            QMessageBox.information(self, "Import", "No QSO records found in the file.")
            return

        reply = QMessageBox.question(
            self, "Import ADIF",
            f"Import {len(records)} QSO record(s) from:\n{filepath}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        imported = 0
        skipped = 0
        for adif_record in records:
            db_record = adif.adif_to_db_record(adif_record)
            errors = adif.validate_qso(db_record)
            if errors:
                skipped += 1
                continue
            try:
                self.db.add_qso(**db_record)
                imported += 1
            except Exception:
                skipped += 1

        self._refresh_table()
        msg = f"Imported {imported} QSOs."
        if skipped:
            msg += f" Skipped {skipped} invalid records."
        self.statusBar().showMessage(msg, 5000)

    # ── N3FJP AC Log Transfer ─────────────────────────────────────

    def _get_selected_qso_ids(self):
        """Return list of QSO IDs from all selected rows."""
        ids = []
        seen_rows = set()
        for idx in self.table.selectedIndexes():
            row = idx.row()
            if row in seen_rows:
                continue
            seen_rows.add(row)
            item = self.table.item(row, 2)  # Date column stores ID
            if item:
                qso_id = item.data(Qt.UserRole)
                if qso_id is not None:
                    ids.append(qso_id)
        return ids

    def _qso_to_adif_string(self, qso):
        """Generate an ADIF record string for a single QSO (no header, no eor)."""
        parts = []
        for db_col, adif_field in adif.DB_TO_ADIF.items():
            value = qso[db_col] if db_col in qso.keys() else None
            if value is None:
                continue
            if isinstance(value, (int, float)) and value == 0:
                if db_col == "freq":
                    continue
            elif isinstance(value, str) and value.strip() == "":
                continue
            if db_col == "freq" and isinstance(value, (int, float)):
                value = f"{value:.6f}".rstrip("0").rstrip(".")
            else:
                value = str(value).strip()
            parts.append(adif._write_field(adif_field, value))
        return " ".join(parts)

    def _send_to_n3fjp(self, qso_ids):
        """Send a list of QSOs to N3FJP AC Log via a single TCP connection."""
        host = config.get("n3fjp_host") or ""
        port = config.get("n3fjp_port") or 1100
        if not host:
            QMessageBox.warning(
                self, "AC Log Transfer",
                "N3FJP AC Log host is not configured.\n\n"
                "Go to Settings to enter the IP address of your Windows machine.",
            )
            return

        # Confirm
        reply = QMessageBox.question(
            self, "Send to AC Log",
            f"Send {len(qso_ids)} QSO(s) to N3FJP AC Log at {host}:{port}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        sent = 0
        errors = 0
        try:
            with N3FJPConnection(host, port) as conn:
                for qso_id in qso_ids:
                    qso = self.db.get_qso(qso_id)
                    if not qso:
                        errors += 1
                        continue
                    adif_str = self._qso_to_adif_string(qso)
                    try:
                        conn.send_adif_record(adif_str)
                        sent += 1
                        self.db.mark_sent_to_aclog(qso_id)
                    except Exception:
                        errors += 1
                    QApplication.processEvents()
        except Exception as e:
            QMessageBox.critical(
                self, "AC Log Transfer",
                f"Failed to connect to AC Log:\n{e}",
            )
            if sent > 0:
                self._refresh_table()
            return

        self._refresh_table()
        msg = f"Sent {sent} QSO(s) to AC Log."
        if errors:
            msg += f" {errors} failed."
        self.statusBar().showMessage(msg, 5000)

    def _send_selected_to_n3fjp(self):
        ids = self._get_selected_qso_ids()
        if not ids:
            QMessageBox.information(
                self, "Send to AC Log",
                "No QSOs selected.\n\n"
                "Select rows in the table first (Ctrl+click or Shift+click),\n"
                "or use 'Send All to AC Log' to send everything.",
            )
            return
        self._send_to_n3fjp(ids)

    def _send_all_to_n3fjp(self):
        qsos = self.db.get_all_qsos_for_export()
        if not qsos:
            QMessageBox.information(self, "Send to AC Log", "No QSOs to send.")
            return
        ids = [q["id"] for q in qsos]
        self._send_to_n3fjp(ids)

    # ── POTA ───────────────────────────────────────────────────────

    def _toggle_pota_mode(self, _checked=False):
        if self._pota_mode:
            # Already active — clicking again deactivates
            self._pota_mode = False
            self._pota_activation = None
            self._pota_mode_btn.setChecked(False)
            self._pota_mode_btn.setStyleSheet("")
            self.statusBar().showMessage("POTA Activation ended.", 3000)
        else:
            dlg = POTAActivationDialog(self, current=self._pota_activation)
            if dlg.exec() == QDialog.Accepted:
                self._pota_activation = dlg.get_data()
                self._pota_mode = True
                self._pota_mode_btn.setChecked(True)
                park = self._pota_activation["my_sig_info"]
                self._pota_mode_btn.setStyleSheet(
                    "background-color: #2E7D32; color: white; font-weight: bold;"
                )
                self.statusBar().showMessage(
                    f"POTA Activation active — {park}", 5000
                )
            else:
                self._pota_mode_btn.setChecked(False)

    def _add_qso_from_pota_spot(self, spot_data):
        # Hunting: activator's park goes in SIG/SIG_INFO (other station's activity).
        # MY_SIG/home QTH come from pota_activation if an activation is in progress.
        dlg = QSODialog(self, flrig_state=self._get_flrig_state(),
                        pota_mode=self._pota_mode,
                        pota_activation=self._pota_activation)
        # Pre-fill from spot — suppress freq/band auto-update during setup
        dlg.call_edit.setText(spot_data.get("call", ""))
        dlg._suppress_auto = True
        freq_mhz = spot_data.get("freq_mhz", 0.0)
        if freq_mhz:
            dlg.freq_spin.setValue(freq_mhz)
        band = spot_data.get("band", "")
        if band:
            idx = dlg.band_combo.findText(band)
            if idx >= 0:
                dlg.band_combo.setCurrentIndex(idx)
        dlg._suppress_auto = False
        idx = dlg.mode_combo.findText(spot_data.get("mode", "SSB"))
        if idx >= 0:
            dlg.mode_combo.setCurrentIndex(idx)
        # Activator's park goes in SIG/SIG_INFO, not MY_SIG/MY_SIG_INFO
        dlg.sig_edit.setText("POTA")
        dlg.sig_info_edit.setText(spot_data.get("park_ref", ""))
        dlg._lookup_callsign()  # auto-populate name/QTH before dialog opens
        dlg.call_edit.setFocus()

        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            self.db.add_qso(**data)
            self._refresh_table()
            self.statusBar().showMessage("QSO added.", 3000)

    def _open_pota_spots(self):
        # Store reference to prevent garbage collection; WA_DeleteOnClose cleans up on close
        self._pota_spots_dlg = POTASpotsDialog(
            self,
            flrig_host=config.get("flrig_host") or "localhost",
            flrig_port=config.get("flrig_port") or 12345,
        )
        self._pota_spots_dlg.qso_requested.connect(self._add_qso_from_pota_spot)
        self._pota_spots_dlg.setAttribute(Qt.WA_DeleteOnClose)
        self._pota_spots_dlg.show()

    # ── FCC Database ──────────────────────────────────────────────

    def _open_fcc_dialog(self):
        dlg = FCCDatabaseDialog(self)
        dlg.exec()

    def _check_fcc_staleness(self):
        if not fcc_db.is_stale():
            return
        last = fcc_db.get_last_updated()
        if last is None:
            msg = (
                "No FCC callsign database found.\n\n"
                "Download it now for offline callsign lookup when QRZ is unavailable?\n"
                "(~18 MB, takes about 30 seconds)"
            )
        else:
            age = (datetime.now(timezone.utc) - last).days
            msg = (
                f"Your FCC callsign database is {age} days old.\n\n"
                "Refresh it now for up-to-date offline callsign lookup?\n"
                "(~18 MB, takes about 30 seconds)"
            )
        reply = QMessageBox.question(self, "FCC Database", msg)
        if reply == QMessageBox.Yes:
            self._open_fcc_dialog()

    # ── New Database ───────────────────────────────────────────────

    def _new_database(self):
        utc_now = datetime.now(timezone.utc)
        timestamp = utc_now.strftime("%Y%m%d_%H%M%S")
        new_name = f"amateur_radio_{timestamp}.db"
        db_dir = os.path.dirname(self.db.db_path)
        new_path = os.path.join(db_dir, new_name)

        reply = QMessageBox.question(
            self, "New Database",
            f"Create a new empty database?\n\n"
            f"File: {new_name}\n\n"
            f"Your current database will not be modified.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.db.close()
        config.set("db_path", new_path)
        self.db = Database(new_path)
        self._refresh_table()
        self.statusBar().showMessage(f"Database: {self.db.db_path}")

    # ── Settings ───────────────────────────────────────────────────

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.Accepted:
            new_path = dlg.get_new_db_path()
            if new_path is not None:
                old_path = self.db.db_path
                if new_path != old_path:
                    if dlg.should_copy() and os.path.exists(old_path):
                        self.db.close()
                        shutil.copy2(old_path, new_path)
                    else:
                        self.db.close()
                    self.db = Database(new_path if new_path else config.get_db_path())
                    self._refresh_table()
                    self.statusBar().showMessage(f"Database: {self.db.db_path}")

            # Restart flrig timer with potentially new settings
            self._flrig_fail_count = 0

            self.statusBar().showMessage("Settings saved.", 3000)

    # ── Theme ──────────────────────────────────────────────────────

    def _change_theme(self):
        action = self.sender()
        if action:
            theme_key = action.data()
            config.set("theme", theme_key)
            apply_theme(QApplication.instance(), theme_key)

    # ── Backup ─────────────────────────────────────────────────────

    def _backup_database(self):
        db_path = self.db.db_path
        if not os.path.exists(db_path):
            return

        backup_dir = os.path.join(os.path.dirname(db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = os.path.splitext(os.path.basename(db_path))[0]
        backup_path = os.path.join(backup_dir, f"{base_name}_{timestamp}.db")

        try:
            shutil.copy2(db_path, backup_path)
        except OSError:
            return

        # Remove old backups beyond max
        max_backups = config.get("max_backups") or 5
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith(base_name) and f.endswith(".db")],
            reverse=True,
        )
        for old in backups[max_backups:]:
            try:
                os.remove(os.path.join(backup_dir, old))
            except OSError:
                pass

    def closeEvent(self, event):
        if config.get("auto_backup"):
            self._backup_database()
        self._flrig_timer.stop()
        self._clock_timer.stop()
        self.db.close()
        event.accept()


# ════════════════════════════════════════════════════════════════════
#  Database Path Resolution
# ════════════════════════════════════════════════════════════════════

def _resolve_db_path():
    """Return a validated database path, prompting if the configured path is missing."""
    db_path = config.get_db_path()
    db_dir = os.path.dirname(db_path)

    if db_dir and not os.path.exists(db_dir):
        # Configured directory doesn't exist — reset to default
        config.set("db_path", "")
        db_path = config.get_db_path()

    return db_path


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("W0BCQ Logger")
    app.setOrganizationName("RadioLog")

    # Set application icon if available
    icon_path = _resource_path("icon_256.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Use Fusion style for consistent cross-platform look
    app.setStyle("Fusion")

    # Apply saved color theme
    apply_theme(app, config.get("theme") or "system")

    # Load database
    db_path = _resolve_db_path()
    db = Database(db_path)

    window = MainWindow(db)
    window.show()

    # Prompt to refresh FCC database if missing or stale (after UI is visible)
    QTimer.singleShot(500, window._check_fcc_staleness)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
