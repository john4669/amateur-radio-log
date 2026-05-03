"""
database.py - SQLite database operations for Amateur Radio Contact Log
"""

import sqlite3


class Database:
    def __init__(self, db_path="amateur_radio.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS qsos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call TEXT NOT NULL,
                qso_date TEXT NOT NULL,
                time_on TEXT NOT NULL,
                time_off TEXT DEFAULT '',
                band TEXT DEFAULT '',
                freq REAL DEFAULT 0.0,
                mode TEXT DEFAULT '',
                rst_sent TEXT DEFAULT '',
                rst_rcvd TEXT DEFAULT '',
                tx_pwr TEXT DEFAULT '',
                name TEXT DEFAULT '',
                qth TEXT DEFAULT '',
                state TEXT DEFAULT '',
                country TEXT DEFAULT '',
                gridsquare TEXT DEFAULT '',
                operator TEXT DEFAULT '',
                my_gridsquare TEXT DEFAULT '',
                my_city TEXT DEFAULT '',
                my_state TEXT DEFAULT '',
                my_country TEXT DEFAULT '',
                sig TEXT DEFAULT '',
                sig_info TEXT DEFAULT '',
                my_sig TEXT DEFAULT '',
                my_sig_info TEXT DEFAULT '',
                comment TEXT DEFAULT '',
                sent_to_aclog INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Migrate older schemas
        cursor.execute("PRAGMA table_info(qsos)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col, definition in [
            ("my_gridsquare", "TEXT DEFAULT ''"),
            ("my_city",       "TEXT DEFAULT ''"),
            ("my_state",      "TEXT DEFAULT ''"),
            ("my_country",    "TEXT DEFAULT ''"),
            ("sig",           "TEXT DEFAULT ''"),
            ("sig_info",      "TEXT DEFAULT ''"),
            ("sent_to_aclog", "INTEGER DEFAULT 0"),
        ]:
            if col not in existing_cols:
                cursor.execute(f"ALTER TABLE qsos ADD COLUMN {col} {definition}")

        self.conn.commit()

    # ── QSO Operations ──────────────────��──────────────────────────

    def add_qso(self, call, qso_date, time_on, time_off="", band="",
                freq=0.0, mode="", rst_sent="", rst_rcvd="", tx_pwr="",
                name="", qth="", state="", country="", gridsquare="",
                operator="", my_gridsquare="", my_city="", my_state="",
                my_country="", sig="", sig_info="", my_sig="",
                my_sig_info="", comment=""):
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT INTO qsos
               (call, qso_date, time_on, time_off, band, freq, mode,
                rst_sent, rst_rcvd, tx_pwr, name, qth, state, country,
                gridsquare, operator, my_gridsquare, my_city, my_state,
                my_country, sig, sig_info, my_sig, my_sig_info, comment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (call, qso_date, time_on, time_off, band, freq, mode,
             rst_sent, rst_rcvd, tx_pwr, name, qth, state, country,
             gridsquare, operator, my_gridsquare, my_city, my_state,
             my_country, sig, sig_info, my_sig, my_sig_info, comment),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_qso(self, qso_id, call, qso_date, time_on, time_off="",
                   band="", freq=0.0, mode="", rst_sent="", rst_rcvd="",
                   tx_pwr="", name="", qth="", state="", country="",
                   gridsquare="", operator="", my_gridsquare="",
                   my_city="", my_state="", my_country="",
                   sig="", sig_info="", my_sig="", my_sig_info="",
                   comment=""):
        self.conn.execute(
            """UPDATE qsos
               SET call=?, qso_date=?, time_on=?, time_off=?, band=?,
                   freq=?, mode=?, rst_sent=?, rst_rcvd=?, tx_pwr=?,
                   name=?, qth=?, state=?, country=?, gridsquare=?,
                   operator=?, my_gridsquare=?, my_city=?, my_state=?,
                   my_country=?, sig=?, sig_info=?, my_sig=?,
                   my_sig_info=?, comment=?
               WHERE id=?""",
            (call, qso_date, time_on, time_off, band, freq, mode,
             rst_sent, rst_rcvd, tx_pwr, name, qth, state, country,
             gridsquare, operator, my_gridsquare, my_city, my_state,
             my_country, sig, sig_info, my_sig, my_sig_info,
             comment, qso_id),
        )
        self.conn.commit()

    def delete_qso(self, qso_id):
        self.conn.execute("DELETE FROM qsos WHERE id=?", (qso_id,))
        self.conn.commit()

    def mark_sent_to_aclog(self, qso_id):
        self.conn.execute(
            "UPDATE qsos SET sent_to_aclog=1 WHERE id=?", (qso_id,)
        )
        self.conn.commit()

    def get_qsos(self, sort_column="qso_date", sort_order="DESC"):
        allowed_columns = {"qso_date", "call", "freq", "band", "mode",
                           "name", "qth", "time_on"}
        if sort_column not in allowed_columns:
            sort_column = "qso_date"
        if sort_order not in ("ASC", "DESC"):
            sort_order = "DESC"

        query = f"""SELECT * FROM qsos
                    ORDER BY {sort_column} {sort_order}, time_on {sort_order}"""
        return self.conn.execute(query).fetchall()

    def get_qso(self, qso_id):
        return self.conn.execute(
            "SELECT * FROM qsos WHERE id=?", (qso_id,)
        ).fetchone()

    def get_all_qsos_for_export(self):
        return self.conn.execute(
            "SELECT * FROM qsos ORDER BY qso_date ASC, time_on ASC"
        ).fetchall()

    # ── Summary / Stats ───────���────────────────────────��────────────

    def get_summary(self):
        row = self.conn.execute(
            """SELECT COUNT(*) as count,
                      MIN(qso_date) as first_date,
                      MAX(qso_date) as last_date
               FROM qsos"""
        ).fetchone()
        summary = dict(row)

        # Top modes
        modes = self.conn.execute(
            """SELECT mode, COUNT(*) as cnt FROM qsos
               WHERE mode != '' GROUP BY mode ORDER BY cnt DESC LIMIT 3"""
        ).fetchall()
        summary["top_modes"] = [(m["mode"], m["cnt"]) for m in modes]

        # Unique callsigns
        unique = self.conn.execute(
            "SELECT COUNT(DISTINCT call) as unique_calls FROM qsos"
        ).fetchone()
        summary["unique_calls"] = unique["unique_calls"]

        return summary

    def close(self):
        self.conn.close()
