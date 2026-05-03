"""
adif.py - ADIF (Amateur Data Interchange Format) read/write for .adi files.

Supports ADIF version 3.1.4. Produces standard-compliant output that
imports cleanly into N3FJP Amateur Contact Log and other logging software.
"""

import re
from datetime import datetime, timezone

ADIF_VER = "3.1.4"
PROGRAM_ID = "W0BCQLogger"
PROGRAM_VERSION = "0.1.0"

# Regex to match an ADIF field tag: <FIELDNAME:length[:type]>
FIELD_RE = re.compile(r"<(\w+):(\d+)(?::(\w))?>", re.IGNORECASE)

# Database column → ADIF field name mapping
DB_TO_ADIF = {
    "call": "CALL",
    "qso_date": "QSO_DATE",
    "time_on": "TIME_ON",
    "time_off": "TIME_OFF",
    "band": "BAND",
    "freq": "FREQ",
    "mode": "MODE",
    "rst_sent": "RST_SENT",
    "rst_rcvd": "RST_RCVD",
    "tx_pwr": "TX_PWR",
    "name": "NAME",
    "qth": "QTH",
    "state": "STATE",
    "country": "COUNTRY",
    "gridsquare": "GRIDSQUARE",
    "operator": "OPERATOR",
    "sig": "SIG",
    "sig_info": "SIG_INFO",
    "my_gridsquare": "MY_GRIDSQUARE",
    "my_city": "MY_CITY",
    "my_state": "MY_STATE",
    "my_country": "MY_COUNTRY",
    "my_sig": "MY_SIG",
    "my_sig_info": "MY_SIG_INFO",
    "comment": "COMMENT",
}

# Reverse mapping for import: lowercase ADIF field → DB column
ADIF_TO_DB = {v.lower(): k for k, v in DB_TO_ADIF.items()}


def _write_field(name, value):
    """Format a single ADIF field tag: <NAME:len>value"""
    value = str(value)
    return f"<{name}:{len(value)}>{value}"


def write_adif(filepath, qsos, header_comment=""):
    """Write QSO records to an ADIF .adi file.

    Args:
        filepath: Output file path.
        qsos: Iterable of dict-like objects (sqlite3.Row or dict) with DB column names.
        header_comment: Optional comment line in the header.

    Returns:
        Number of records written.
    """
    with open(filepath, "w", encoding="utf-8") as f:
        # Header
        f.write("W0BCQ Logger - ADIF Export\n")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        f.write(f"Generated: {ts}\n")
        if header_comment:
            f.write(f"{header_comment}\n")
        f.write("\n")
        f.write(_write_field("ADIF_VER", ADIF_VER) + "\n")
        f.write(_write_field("PROGRAMID", PROGRAM_ID) + "\n")
        f.write(_write_field("PROGRAMVERSION", PROGRAM_VERSION) + "\n")
        f.write("<eoh>\n\n")

        # Records
        count = 0
        for qso in qsos:
            parts = []
            for db_col, adif_field in DB_TO_ADIF.items():
                value = qso[db_col] if db_col in qso.keys() else None

                # Skip empty values
                if value is None:
                    continue
                if isinstance(value, (int, float)) and value == 0:
                    # Skip zero freq but keep other zero-like values if they're strings
                    if db_col == "freq":
                        continue
                elif isinstance(value, str) and value.strip() == "":
                    continue

                # Format frequency without trailing zeros
                if db_col == "freq" and isinstance(value, (int, float)):
                    value = f"{value:.6f}".rstrip("0").rstrip(".")

                parts.append(_write_field(adif_field, value))

            if parts:
                f.write(" ".join(parts) + " <eor>\n")
                count += 1

    return count


def _parse_fields(text):
    """Extract ADIF fields from a block of text.

    Returns:
        Dict of lowercase field_name → string value.
    """
    fields = {}
    for match in FIELD_RE.finditer(text):
        name = match.group(1).lower()
        length = int(match.group(2))
        start = match.end()
        value = text[start:start + length]
        fields[name] = value
    return fields


def read_adif(filepath):
    """Read an ADIF .adi file and return a list of QSO dicts.

    Each dict has lowercase ADIF field names as keys.
    Unknown fields are preserved in the returned dicts.

    Returns:
        List of dicts, one per QSO record.
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Split header from body
    eoh_match = re.search(r"<eoh>", content, re.IGNORECASE)
    if eoh_match:
        body = content[eoh_match.end():]
    else:
        body = content

    # Split into records
    records = re.split(r"<eor>", body, flags=re.IGNORECASE)
    qsos = []
    for record_text in records:
        record_text = record_text.strip()
        if not record_text:
            continue
        fields = _parse_fields(record_text)
        if fields:
            qsos.append(fields)

    return qsos


def adif_to_db_record(adif_fields):
    """Convert an ADIF field dict (from read_adif) to a DB column dict.

    Only maps fields that have corresponding DB columns.
    Handles freq as float conversion.

    Returns:
        Dict with DB column names as keys.
    """
    record = {}
    for adif_name, value in adif_fields.items():
        db_col = ADIF_TO_DB.get(adif_name)
        if db_col:
            if db_col == "freq":
                try:
                    record[db_col] = float(value)
                except (ValueError, TypeError):
                    record[db_col] = 0.0
            else:
                record[db_col] = value.strip()
    return record


def validate_qso(qso_dict):
    """Validate required fields for a QSO record.

    Args:
        qso_dict: Dict with DB column names (or lowercase ADIF field names).

    Returns:
        List of error strings. Empty list means valid.
    """
    errors = []

    # Check for call (required)
    call = qso_dict.get("call", "").strip()
    if not call:
        errors.append("Call sign is required")

    # Check for date (required)
    qso_date = qso_dict.get("qso_date", "").strip()
    if not qso_date:
        errors.append("Date is required")
    elif len(qso_date) != 8 or not qso_date.isdigit():
        errors.append("Date must be in YYYYMMDD format")

    # Check for time (required)
    time_on = qso_dict.get("time_on", "").strip()
    if not time_on:
        errors.append("Time is required")
    elif len(time_on) not in (4, 6) or not time_on.isdigit():
        errors.append("Time must be in HHMM or HHMMSS format")

    # Check for mode (required)
    mode = qso_dict.get("mode", "").strip()
    if not mode:
        errors.append("Mode is required")

    # Need at least band or freq
    band = qso_dict.get("band", "").strip()
    freq = qso_dict.get("freq", 0)
    if isinstance(freq, str):
        try:
            freq = float(freq)
        except (ValueError, TypeError):
            freq = 0
    if not band and freq == 0:
        errors.append("Band or frequency is required")

    return errors
