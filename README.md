# W0BCQ Logger

A lightweight desktop application for logging amateur radio contacts on Linux, macOS, and Windows. Stores QSOs in SQLite and exports standard ADIF files for import into [N3FJP's Amateur Contact Log](https://www.n3fjp.com/aclog.html) or other logging software. Can also transfer QSOs directly to AC Log over your LAN.

Built with PySide6 (Qt6) and Python.

## Features

- **QSO Logging** — Form-based entry with call sign, frequency, band, mode, RST, and more. All times default to UTC.
- **flrig Integration** — Polls [flrig](http://www.w1hkj.com/) every 2 seconds (in the background, so the interface stays responsive even if the radio is slow or flrig isn't running) for your radio's current frequency and mode. New QSOs are automatically populated from the radio. Connection status is shown in the status bar.
- **QRZ Callsign Lookup** — When you enter a call sign, the app queries [QRZ.com](https://www.qrz.com/) and auto-fills the operator's name, QTH, state, country, and grid square. Requires a QRZ XML Logbook Data subscription. Falls back to the local FCC database if QRZ is unavailable or not configured.
- **Offline FCC Database** — Download the FCC ULS amateur license database (~18 MB) for offline callsign lookups. The app prompts you to refresh when the data is more than 30 days old. Accessed via **File > Update FCC Database**.
- **POTA Activation** — Activate POTA mode with a park reference, city, state/country, and grid square. These session-only settings override your home QTH defaults and are stamped on every QSO logged during the activation. The button stays green while active. During an activation, the Add QSO dialog moves the **Their Park** field up beneath the call sign and auto-tags the contact as POTA when you enter a park reference — for fast park-to-park logging.
- **ADIF Export/Import** — Exports standard ADIF 3.1.4 `.adi` files compatible with N3FJP AC Log, LoTW, QRZ, and other software. Can also import ADIF files from other sources.
- **N3FJP AC Log Transfer** — Send selected or all QSOs directly to AC Log running on a Windows machine over your home network using N3FJP's TCP API.
- **Transfer Tracking** — A "Sent" indicator in the log table shows which QSOs have already been transferred to AC Log.
- **New Database** — Start a fresh database after transferring your QSOs, keeping your workflow clean.
- **Frequency/Band Auto-Mapping** — Entering a frequency automatically selects the correct band, and vice versa.
- **RST Defaults by Mode** — 59 for phone (SSB, FM, AM), 599 for CW, -10 for digital (FT8, FT4).
- **Duplicate QSO** — Quickly log similar contacts by duplicating an existing QSO with a fresh timestamp.
- **8 Color Themes** — System, Light, Dark, Sky Blue, Sage Green, Warm Sand, Lavender, and Soft Rose.
- **Auto-Backup** — Database is automatically backed up on close.

## Requirements

- Python 3.8+
- PySide6
- Linux, macOS, or Windows

### Optional

- **flrig** — Must be running for automatic frequency/mode population. Download from [w1hkj.com](http://www.w1hkj.com/). flrig's XML-RPC server listens on port 12345 by default.
- **QRZ.com account** — XML Logbook Data subscription required for callsign lookups.
- **N3FJP Amateur Contact Log** — Running on a Windows machine with the TCP API enabled (Settings > Application Program Interface > TCP API Enabled, default port 1100).

## Installation

### Windows (prebuilt — no Python needed)

Download the latest `W0BCQ_Logger-*-windows-x64.zip` from the
[Releases](https://github.com/john4669/amateur-radio-log/releases) page,
unzip it, and run `W0BCQ_Logger.exe`. Keep the `_internal` folder next to
the `.exe` — the app needs it.

### From source (Linux, macOS, or Windows)

```bash
git clone https://github.com/john4669/amateur-radio-log.git
cd amateur-radio-log
```

Then run the first-time setup for your platform:

- **Linux / macOS:** `./setup.sh`
- **Windows:** `setup.bat` (or double-click it)

This creates a Python virtual environment and installs PySide6.

### Building the Windows executable

To produce a standalone Windows build (the same one distributed on the
Releases page), run on Windows:

```
build-windows.bat
```

This creates a fresh virtual environment, installs the build tools, and
runs PyInstaller against `W0BCQ_Logger.spec`. The result is in
`dist\W0BCQ_Logger\` — distribute the **whole folder** (the `.exe` needs
its `_internal` folder alongside it).

## Usage

### Launch the App

- **Linux / macOS:** `./RadioLog.sh`
- **Windows:** run `RadioLog.bat` (or double-click it)

Or create a desktop shortcut:

**Linux:**
```bash
./create-shortcut-linux.sh
```

**macOS:**
```bash
./create-shortcut-mac.sh
```
This creates a `W0BCQ Logger.app` bundle in the project folder. Drag it to your Desktop or Applications folder. On first launch, right-click > Open if macOS shows a security warning.

**Windows:**
Right-click `RadioLog.bat` > **Send to > Desktop (create shortcut)**. To give the shortcut the app icon, open its **Properties > Change Icon** and point it at `icon.ico` in the project folder.

### First-Time Setup

Go to **File > Settings** and configure:

1. **Operator Defaults** — Your callsign, grid square, and default TX power.
2. **flrig Connection** — Host and port (default: localhost:12345). flrig must be running and connected to your radio for automatic frequency/mode population.
3. **QRZ Callsign Lookup** — Your QRZ username and password. Use "Test Login" to verify.
4. **N3FJP AC Log** — The IP address of your Windows machine running AC Log and the API port (default: 1100).

### Logging Contacts

1. Click **Add QSO** (or press **Ctrl+N** / **F2**). If flrig is running, the frequency, band, and mode are pre-filled from your radio.
2. Enter the call sign and press Tab. If QRZ is configured, the operator's name and location are filled automatically.
3. Fill in any remaining fields and click **Save**.
4. Use **Duplicate QSO** (Ctrl+D) to quickly log similar contacts — it copies all fields from the selected QSO but refreshes the date/time and clears the call sign.

### Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Add QSO | Ctrl+N or F2 |
| Duplicate QSO | Ctrl+D |
| Delete QSO | Delete |
| Export all to ADIF | Ctrl+E |
| Import ADIF | Ctrl+I |
| Quit | Ctrl+Q |

### Transferring to N3FJP AC Log

There are two ways to get your QSOs into AC Log on Windows:

**Direct Transfer (recommended):**
1. Ensure AC Log is running on your Windows machine with the TCP API enabled.
2. Select QSOs in the table (Ctrl+click or Shift+click for multiple), then **File > Send Selected to AC Log**. Or use **File > Send All to AC Log**.
3. A green "Y" appears in the Sent column for each successfully transferred QSO.
4. From AC Log, upload to QRZ and/or LoTW as usual.

**ADIF File Export:**
1. **File > Export to ADIF** (Ctrl+E) to save a `.adi` file.
2. Copy the file to your Windows machine.
3. In AC Log, use **File > Import ADIF** to load the contacts.

### Starting Fresh

After transferring your QSOs to AC Log, use **File > New Database** to start a fresh log. The old database file is kept in the app folder with a UTC timestamp in the filename.

## Typical Workflow

1. Start flrig and connect to your radio.
2. Launch W0BCQ Logger.
3. Work stations — log each QSO as you go.
4. When done, send all QSOs to AC Log over the LAN.
5. In AC Log, upload to QRZ/LoTW.
6. Start a new database for the next session.

## File Structure

```
amateur-radio-log/
├── main.py                    # Application UI and logic
├── database.py                # SQLite database operations
├── adif.py                    # ADIF file read/write
├── config.py                  # JSON settings management
├── fcc_db.py                  # FCC ULS database download and offline lookup
├── requirements.txt           # Python dependencies
├── setup.sh / setup.bat       # First-time setup (Linux-macOS / Windows)
├── RadioLog.sh / RadioLog.bat # Launcher (Linux-macOS / Windows)
├── create-shortcut-linux.sh   # Desktop shortcut creator (Linux)
├── create-shortcut-mac.sh     # App bundle creator (macOS)
├── build-windows.bat          # Builds the Windows .exe (PyInstaller)
├── W0BCQ_Logger.spec          # PyInstaller build spec
├── icon_256.png / icon.ico    # Application icon (PNG / Windows ICO)
└── .gitignore
```

## License

Copyright &copy; 2026 John Friede (W0BCQ)

Licensed under [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)](https://creativecommons.org/licenses/by-nc-sa/4.0/).

Free to use, share, and adapt for non-commercial purposes. Derivatives must carry the same license.
