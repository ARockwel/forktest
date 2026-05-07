"""
db.py — Database connection singleton (Windows Authentication only).

Loads plant configuration from plants.json.
All query modules import the shared `db` instance from here.
"""

import json
import os
from dataclasses import dataclass

try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False

# Path to config file — same directory as this script
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "plants.json")


# ═══════════════════════════════════════════════════════════════════════════════
#  PLANT CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class Plant:
    name:        str
    code:        str
    server:      str
    database:    str
    environment: str   # "PROD" | "QA" | "IWS"
    notes:       str


def load_plants() -> tuple[list[Plant], str]:
    """
    Read plants.json and return (plants_list, error_message).
    error_message is empty on success.
    """
    if not os.path.exists(_CONFIG_PATH):
        return [], f"plants.json not found at:\n{_CONFIG_PATH}"
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        plants = []
        for entry in raw.get("plants", []):
            plants.append(Plant(
                name        = entry.get("name",        "Unnamed Plant"),
                code        = entry.get("code",        "???"),
                server      = entry.get("server",      ""),
                database    = entry.get("database",    ""),
                environment = entry.get("environment", "PROD"),
                notes       = entry.get("notes",       ""),
            ))
        if not plants:
            return [], "plants.json contains no plant entries."
        return plants, ""
    except Exception as exc:
        return [], f"Failed to parse plants.json:\n{exc}"


# ═══════════════════════════════════════════════════════════════════════════════
#  DATABASE CONNECTION
# ═══════════════════════════════════════════════════════════════════════════════
class Database:
    def __init__(self):
        self.conn          = None
        self.active_plant: Plant | None = None
        self.cancelled     = False   # set True on disconnect to abort running queries

    def connect(self, plant: Plant) -> tuple[bool, str]:
        if not PYODBC_AVAILABLE:
            return False, "pyodbc is not installed.\nRun:  pip install pyodbc"
        try:
            conn_str = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={plant.server};"
                f"DATABASE={plant.database};"
                f"Trusted_Connection=yes;"
                f"MARS_Connection=yes;"
            )
            self.cancelled = False
            self.conn = pyodbc.connect(conn_str, timeout=10)
            self.active_plant = plant
            return True, "Connected successfully."
        except Exception as exc:
            self.conn         = None
            self.active_plant = None
            return False, str(exc)

    def disconnect(self):
        self.cancelled = True   # signal all running queries to abort
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
        self.conn         = None
        self.active_plant = None

    @property
    def connected(self) -> bool:
        return self.conn is not None


# Shared singleton — imported by all query modules
db = Database()
