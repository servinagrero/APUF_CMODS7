#!/usr/bin/env python3

import logging
import random
import sqlite3
import sys
import time
from importlib.resources import files

from .fpga_device import FPGADevice, discover_hardware

__all__ = [
    "FPGADevice",
    "discover_hardware",
    "get_db_connection",
    "initialize_database",
    "execute_with_retry",
    "setup_master_logger",
    "setup_worker_logger",
]


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create the acquisition tables in an open SQLite connection."""
    schema = files("apuf").joinpath("schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema)


def get_db_connection(db_path):
    """
    Optimized SQLite connection specifically designed to maximize throughput
    and minimize mechanical head thrashing on HDDs.
    """
    con = sqlite3.connect(db_path, timeout=30.0)
    # Single writer per file means no contention
    con.execute("PRAGMA journal_mode=DELETE;")
    # OFF or NORMAL reduces disk synchronization barriers completely
    con.execute("PRAGMA synchronous=OFF;")
    # Cache up to ~128MB of data in RAM before hitting the HDD platters
    con.execute("PRAGMA cache_size=-128000;")
    con.execute("PRAGMA temp_store=MEMORY;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def execute_with_retry(cursor, sql, records, max_retries=5):
    """
    Executes a SQLite query and if it fails, sleeps and tries again until a maximum of `max_retries`

    Sleep an exponential random duration to spread out insertion traffic, specially if multiple queries are sent at the same time from each worker
    """
    for attempt in range(max_retries):
        try:
            cursor.executemany(sql, records)
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep((2**attempt) + random.uniform(0, 1))
            else:
                raise e


def setup_master_logger():
    logger = logging.getLogger("orchestrator")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [MASTER] %(levelname)s %(message)s", datefmt="%Y-%m-%d - %H:%M:%S"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def setup_worker_logger(log_file_path=None):
    logger = logging.getLogger("fpga_worker")
    logger.setLevel(logging.INFO)

    # Clear existing handlers to prevent duplicate lines
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    if log_file_path:
        # File handler for running inside background pools
        handler = logging.FileHandler(log_file_path)
    else:
        # Standard fallback for manual/interactive testing
        handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
