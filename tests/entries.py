"""Compact constructors for domain entries, so a test reads like the two files it reconciles."""

import datetime as dt
from decimal import Decimal

from app.domain.entries import Entry

START = dt.date(2026, 10, 1)
LEDGER_IDS = 100_000  # ledger ids are offset so that a mix-up between sides fails loudly


def on(day: int) -> dt.date:
    """Day 1 is 1 October 2026; days past the end of the month run on into November."""
    return START + dt.timedelta(days=day - 1)


def bank(row: int, amount: str, day: int, reference: str = "", description: str = "") -> Entry:
    return Entry(row, row, on(day), Decimal(amount), reference, description)


def ledger(row: int, amount: str, day: int, reference: str = "", description: str = "") -> Entry:
    return Entry(LEDGER_IDS + row, row, on(day), Decimal(amount), reference, description)
