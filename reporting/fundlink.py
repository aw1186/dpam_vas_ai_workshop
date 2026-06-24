"""FundLink Oracle database connection helper.

Reads credentials from ``config.ini`` (kept out of source control) and exposes
small helpers to test connectivity and run read-only queries against the
FundLink data warehouse.
"""
from __future__ import annotations

import configparser
import re
from functools import lru_cache
from pathlib import Path

import oracledb

# config.ini lives next to manage.py (project root).
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"


@lru_cache(maxsize=1)
def _credentials():
    """Load FundLink credentials from config.ini once."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing config file: {CONFIG_PATH}. "
            "Copy config.example.ini to config.ini and fill in credentials."
        )
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    return {
        "user": config.get("fundlink", "username"),
        "password": config.get("fundlink", "password"),
        "dsn": config.get("fundlink", "dsn"),
    }


def get_connection():
    """Open a new Oracle connection to FundLink.

    Caller is responsible for closing it (use as a context manager).
    """
    creds = _credentials()
    return oracledb.connect(
        user=creds["user"],
        password=creds["password"],
        dsn=creds["dsn"],
    )


def test_connection():
    """Return (ok, message) describing whether FundLink is reachable."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM dual")
                cur.fetchone()
        return True, "Connected to FundLink successfully."
    except FileNotFoundError as exc:
        return False, str(exc)
    except oracledb.Error as exc:
        return False, f"Oracle error: {exc}"


def run_query(sql, params=None, limit=200):
    """Execute a read-only SELECT and return (columns, rows).

    A LIMIT-style cap is applied by fetching at most ``limit`` rows so the UI
    never pulls an unbounded result set. ``params`` are bound safely by the
    driver to prevent SQL injection.
    """
    statement = sql.strip().rstrip(";")
    lowered = statement.lstrip().lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError("Only read-only SELECT (or WITH ... SELECT) statements are allowed.")
    # Block any write/DDL keywords as whole words, even inside a CTE.
    if re.search(r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke)\b",
                 lowered):
        raise ValueError("Only read-only queries are allowed.")

    with get_connection() as conn:
        conn.call_timeout = 60000  # ms; guard against runaway scans on huge tables
        with conn.cursor() as cur:
            cur.execute(statement, params or {})
            columns = [c[0] for c in cur.description]
            rows = cur.fetchmany(limit)
    return columns, rows
