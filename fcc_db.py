"""
fcc_db.py - FCC Amateur Radio License Database for offline callsign lookup.

Downloads the FCC ULS complete amateur radio database (~18 MB compressed),
parses it, and stores active licenses in a local SQLite file for fast
offline lookup.
"""

import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone

FCC_ZIP_URL = "https://data.fcc.gov/download/pub/uls/complete/l_amat.zip"

if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(sys.executable)
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))

FCC_DB_PATH = os.path.join(_APP_DIR, "fcc_amateur.db")

_CLASS_MAP = {
    "E": "Extra",
    "A": "Advanced",
    "G": "General",
    "T": "Technician",
    "N": "Novice",
}

STALE_DAYS = 30


def get_last_updated():
    """Return UTC datetime of last import, or None if database doesn't exist."""
    if not os.path.exists(FCC_DB_PATH):
        return None
    try:
        conn = sqlite3.connect(FCC_DB_PATH)
        row = conn.execute(
            "SELECT value FROM meta WHERE key='last_updated'"
        ).fetchone()
        conn.close()
        if row:
            return datetime.fromisoformat(row[0])
    except Exception:
        pass
    return None


def is_stale():
    """Return True if database is missing or older than STALE_DAYS."""
    last = get_last_updated()
    if last is None:
        return True
    age = (datetime.now(timezone.utc) - last).days
    return age >= STALE_DAYS


def lookup(call):
    """Look up a call sign in the local FCC database.

    Returns a dict with keys: first_name, last_name, city, state, license_class
    or None if not found or database unavailable.
    """
    if not os.path.exists(FCC_DB_PATH):
        return None
    try:
        conn = sqlite3.connect(FCC_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM callsigns WHERE call=?", (call.upper().strip(),)
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


_EXPECTED_BYTES = 20 * 1_048_576  # ~20 MB estimate used when Content-Length absent


def _download_urllib(tmp_path, progress_cb, cancelled_fn):
    """Download via urllib (no socket timeout — runs in background thread)."""
    req = urllib.request.Request(
        FCC_ZIP_URL,
        headers={"User-Agent": "W0BCQLogger/FCC-Import"},
    )
    with urllib.request.urlopen(req) as resp:
        total_bytes = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(tmp_path, "wb") as f:
            while True:
                if cancelled_fn and cancelled_fn():
                    raise InterruptedError("Cancelled")
                chunk = resp.read(32768)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    denom = total_bytes if total_bytes > 0 else _EXPECTED_BYTES
                    pct = min(int(45 * done / denom), 44)
                    mb_done = done / 1_048_576
                    if total_bytes > 0:
                        mb_total = total_bytes / 1_048_576
                        progress_cb(pct, f"Downloading… {mb_done:.1f} / {mb_total:.1f} MB")
                    else:
                        progress_cb(pct, f"Downloading… {mb_done:.1f} MB")


def _download_curl(tmp_path, progress_cb, cancelled_fn):
    """Download via curl subprocess (fallback when urllib fails)."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(
        ["curl", "-L", "-s", "-S", "-o", tmp_path, FCC_ZIP_URL],
        stderr=subprocess.PIPE,
        **kwargs,
    )
    while proc.poll() is None:
        if cancelled_fn and cancelled_fn():
            proc.terminate()
            raise InterruptedError("Cancelled")
        size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
        pct = min(int(45 * size / _EXPECTED_BYTES), 44)
        if progress_cb:
            progress_cb(pct, f"Downloading… {size / 1_048_576:.1f} MB")
        time.sleep(0.5)
    if proc.returncode != 0:
        err = proc.stderr.read().decode(errors="replace").strip()
        raise RuntimeError(f"curl failed: {err}")


def download_and_import(progress_cb=None, cancelled_fn=None):
    """Download the FCC zip and import it into the local database.

    progress_cb(percent: int, message: str)  — called periodically
    cancelled_fn() -> bool                   — return True to abort

    Returns number of callsigns imported.
    Raises on error or cancellation.
    """
    def _check():
        if cancelled_fn and cancelled_fn():
            raise InterruptedError("Cancelled")

    tmp_path = None
    try:
        # ── Phase 1: Download (0-45%) ─────────────────────────────────
        if progress_cb:
            progress_cb(0, "Connecting to FCC…")
        _check()

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
        os.close(tmp_fd)

        try:
            _download_curl(tmp_path, progress_cb, cancelled_fn)
        except InterruptedError:
            raise
        except Exception:
            if progress_cb:
                progress_cb(0, "curl unavailable, trying urllib…")
            _download_urllib(tmp_path, progress_cb, cancelled_fn)

        _check()

        # ── Phase 2: Read active IDs from HD.dat (45-55%) ────────────
        if progress_cb:
            progress_cb(45, "Reading license status…")

        active_ids = set()
        with zipfile.ZipFile(tmp_path) as zf:
            if "HD.dat" in zf.namelist():
                with zf.open("HD.dat") as f:
                    for raw in f:
                        fields = raw.decode("latin-1", errors="replace").split("|")
                        if len(fields) > 5 and fields[5].strip() == "A":
                            active_ids.add(fields[1].strip())

        _check()
        if progress_cb:
            progress_cb(52, f"Found {len(active_ids):,} active licenses…")

        # ── Phase 3: Read license classes from AM.dat (55-60%) ────────
        license_classes = {}
        with zipfile.ZipFile(tmp_path) as zf:
            if "AM.dat" in zf.namelist():
                with zf.open("AM.dat") as f:
                    for raw in f:
                        fields = raw.decode("latin-1", errors="replace").split("|")
                        if len(fields) >= 6:
                            call = fields[4].strip().upper()
                            cls = _CLASS_MAP.get(fields[5].strip(), "")
                            if call and cls:
                                license_classes[call] = cls

        _check()
        if progress_cb:
            progress_cb(58, "Building database…")

        # ── Phase 4: Parse EN.dat and insert (60-97%) ─────────────────
        tmp_db = FCC_DB_PATH + ".tmp"
        if os.path.exists(tmp_db):
            os.remove(tmp_db)

        conn = sqlite3.connect(tmp_db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE callsigns (
                call         TEXT PRIMARY KEY,
                first_name   TEXT DEFAULT '',
                last_name    TEXT DEFAULT '',
                city         TEXT DEFAULT '',
                state        TEXT DEFAULT '',
                license_class TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()

        inserted = 0
        with zipfile.ZipFile(tmp_path) as zf:
            en_size = zf.getinfo("EN.dat").file_size
            processed = 0
            batch = []

            with zf.open("EN.dat") as f:
                for raw in f:
                    _check()
                    processed += len(raw)
                    fields = raw.decode("latin-1", errors="replace").rstrip("\r\n").split("|")
                    if len(fields) < 18:
                        continue
                    if fields[1].strip() not in active_ids:
                        continue
                    call = fields[4].strip().upper()
                    if not call:
                        continue

                    first_name = fields[8].strip().title()
                    last_name  = fields[10].strip().title()
                    city       = fields[16].strip().title()
                    state      = fields[17].strip().upper()
                    lic_class  = license_classes.get(call, "")

                    batch.append((call, first_name, last_name, city, state, lic_class))

                    if len(batch) >= 2000:
                        conn.executemany(
                            "INSERT OR REPLACE INTO callsigns VALUES (?,?,?,?,?,?)",
                            batch,
                        )
                        inserted += len(batch)
                        batch.clear()
                        if progress_cb and en_size > 0:
                            pct = 58 + int(39 * processed / en_size)
                            progress_cb(min(pct, 96), f"Imported {inserted:,} callsigns…")

            if batch:
                conn.executemany(
                    "INSERT OR REPLACE INTO callsigns VALUES (?,?,?,?,?,?)",
                    batch,
                )
                inserted += len(batch)

        if progress_cb:
            progress_cb(97, "Finalizing…")

        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('last_updated', ?)", (now,))
        conn.commit()
        conn.close()

        # Atomically replace the live database
        if os.path.exists(FCC_DB_PATH):
            os.remove(FCC_DB_PATH)
        os.rename(tmp_db, FCC_DB_PATH)

        if progress_cb:
            progress_cb(100, f"Done — {inserted:,} callsigns imported.")

        return inserted

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
