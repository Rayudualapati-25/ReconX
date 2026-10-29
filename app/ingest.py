"""Read a bank statement or ledger CSV into normalised rows, or explain what is wrong with it.

pandas reads every cell as text, so an amount never passes through a binary float: each one is
parsed straight into a Decimal. Dates are read day first, as Indian statements write them.
References are upper-cased and stripped to letters and digits, so "inv/2026-0042" and
"INV 2026 0042" compare equal. Every problem is collected with its row number, and a file with
any problem is refused whole: storing the good rows would turn each bad one into a false
"missing" break.
"""

import datetime as dt
import io
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from app.errors import InvalidFile

MAX_ERRORS_SHOWN = 20
MAX_REFERENCE_LENGTH = 64
PAISA = Decimal("0.01")

# Headers are compared lower-cased, with every run of other characters turned into one
# underscore: "Ref No./Cheque No." becomes "ref_no_cheque_no". When several columns could be
# the same field (a statement with both "Date" and "Value Date"), the earliest alias wins.
COLUMN_ALIASES: Mapping[str, tuple[str, ...]] = {
    "date": (
        "date", "txn_date", "transaction_date", "posting_date", "entry_date", "value_date",
        "value_dt",
    ),
    "amount": ("amount", "amt", "amount_inr"),
    "debit": (
        "debit", "debit_amount", "withdrawal", "withdrawals", "withdrawal_amt",
        "withdrawal_amount", "withdrawal_amount_inr",
    ),
    "credit": (
        "credit", "credit_amount", "deposit", "deposits", "deposit_amt", "deposit_amount",
        "deposit_amount_inr",
    ),
    "reference": (
        "reference", "ref", "ref_no", "reference_no", "reference_number", "payment_reference",
        "utr", "utr_no", "chq_ref_no", "ref_no_cheque_no", "cheque_no", "cheque_number",
    ),
    "description": (
        "description", "narration", "particulars", "details", "memo", "remarks",
        "transaction_remarks",
    ),
}  # fmt: skip
# Day first, as Indian banks write dates. A two-digit year is read as 20xx.
DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d/%m/%y",
    "%d-%m-%y",
)  # fmt: skip

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_CURRENCY = re.compile(r"(?:₹|INR|RS\.?)\s*")
_SIDE = re.compile(r"\s*\b(DR|CR)\.?$")

Problem = tuple[int, str]


@dataclass(frozen=True, slots=True)
class ParsedRow:
    row: int
    date: dt.date
    amount: Decimal
    reference: str
    raw_reference: str
    description: str


def parse_amount(text: str) -> Decimal:
    """One amount, exactly. Money out is negative: "-120", "(120)" and "120 Dr" all mean -120."""
    original = text.strip()
    value = original.upper()
    if not value:
        raise ValueError("amount is missing")
    signs: list[str] = []
    if (side := _SIDE.search(value)) is not None:
        signs.append(side.group(1))
        value = value[: side.start()].strip()
    if value.startswith("(") and value.endswith(")"):
        signs.append("()")
        value = value[1:-1]
    value = _CURRENCY.sub("", value).replace(",", "").replace(" ", "")
    if value[:1] in ("+", "-") and value:
        signs.append(value[0])
        value = value[1:]
    if len(signs) > 1:
        raise ValueError(f"amount '{original}' has more than one sign")
    if not _NUMBER.fullmatch(value):
        raise ValueError(f"amount '{original}' is not a number")
    amount = Decimal(value)
    if amount.quantize(PAISA) != amount:
        raise ValueError(f"amount '{original}' has more than two decimal places")
    if amount == 0:
        raise ValueError("amount is zero")
    negative = bool(signs) and signs[0] in ("-", "()", "DR")
    return -amount.quantize(PAISA) if negative else amount.quantize(PAISA)


def _amount_from_sides(debit: str, credit: str) -> Decimal:
    """A signed amount from a debit column (money out) and a credit column (money in)."""
    if debit.strip() and credit.strip():
        raise ValueError("has both a debit and a credit")
    side, text = ("debit", debit) if debit.strip() else ("credit", credit)
    amount = parse_amount(text)
    if amount < 0:
        raise ValueError(f"{side} must not be negative")
    return -amount if side == "debit" else amount


def _read_frame(content: bytes) -> pd.DataFrame:
    if not content.strip():
        raise InvalidFile("The file is empty.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidFile("The file is not UTF-8 text. Save it as CSV (UTF-8) and retry.") from None
    try:
        frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, index_col=False)
    except pd.errors.ParserError as error:
        raise InvalidFile(f"The file is not valid CSV: {error}") from None
    # Rows of empty cells (",,,") are dropped; the index still counts them, as the file does.
    filled = pd.Series(False, index=frame.index)
    for name in frame.columns:
        filled |= frame[name].str.strip().ne("")
    if not filled.any():
        raise InvalidFile("The file has no rows.")
    return frame.loc[filled]


def _find_columns(headers: Iterable[str]) -> dict[str, str]:
    """The file's column for each field, chosen by the alias lists above."""
    by_name: dict[str, str] = {}
    for header in headers:
        by_name.setdefault(re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_"), header)
    columns = {
        field: next(by_name[alias] for alias in aliases if alias in by_name)
        for field, aliases in COLUMN_ALIASES.items()
        if any(alias in by_name for alias in aliases)
    }
    if "date" not in columns:
        raise InvalidFile(f"No date column: name one of {', '.join(COLUMN_ALIASES['date'])}.")
    if "amount" not in columns and not {"debit", "credit"} <= columns.keys():
        raise InvalidFile(
            "No amount column: name one amount column, or a debit and a credit column."
        )
    return columns


def _parse_dates(column: "pd.Series[str]") -> "pd.Series[pd.Timestamp]":
    """Each value read with the first format in DATE_FORMATS that fits it; NaT if none does."""
    text = column.str.strip()
    parsed = pd.Series(pd.NaT, index=column.index, dtype="datetime64[us]")
    for date_format in DATE_FORMATS:
        todo = parsed.isna()
        if not todo.any():
            break
        parsed[todo] = pd.to_datetime(text[todo], format=date_format, errors="coerce")
    return parsed


def _parse_amounts(
    frame: pd.DataFrame, columns: Mapping[str, str], rows: list[int], problems: list[Problem]
) -> dict[int, Decimal]:
    """Each row's signed amount, from one amount column or from debit and credit columns."""
    cells: list[tuple[str, ...]]
    parse: Callable[..., Decimal]
    if "amount" in columns:
        cells = [(value,) for value in frame[columns["amount"]]]
        parse = parse_amount
    else:
        cells = list(zip(frame[columns["debit"]], frame[columns["credit"]], strict=True))
        parse = _amount_from_sides
    amounts: dict[int, Decimal] = {}
    for row, values in zip(rows, cells, strict=True):
        try:
            amounts[row] = parse(*values)
        except ValueError as error:
            problems.append((row, str(error)))
    return amounts


def _text_column(frame: pd.DataFrame, columns: Mapping[str, str], field: str) -> "pd.Series[str]":
    if field not in columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[columns[field]].str.strip()


def _refuse(problems: list[Problem]) -> InvalidFile:
    problems.sort(key=lambda problem: problem[0])  # stable: a row keeps its checks in order
    rows = len({row for row, _ in problems})
    shown = [f"row {row}: {message}" for row, message in problems[:MAX_ERRORS_SHOWN]]
    count = "1 row has" if rows == 1 else f"{rows} rows have"
    return InvalidFile(f"{count} problems, so nothing was stored.", shown)


def read_statement(content: bytes) -> list[ParsedRow]:
    """Every row of a CSV statement or ledger, normalised; InvalidFile if any row is bad."""
    frame = _read_frame(content)
    columns = _find_columns(frame.columns)
    rows = [int(index) + 1 for index in frame.index.tolist()]  # 1-based data row numbers
    problems: list[Problem] = []

    dates = _parse_dates(frame[columns["date"]])
    for row, text, missing in zip(rows, frame[columns["date"]], dates.isna(), strict=True):
        if missing:
            problems.append((row, f"date '{text.strip()}' is not a date in a supported format"))
    amounts = _parse_amounts(frame, columns, rows, problems)
    raw_references = _text_column(frame, columns, "reference")
    for row, length in zip(rows, raw_references.str.len(), strict=True):
        if length > MAX_REFERENCE_LENGTH:
            problems.append((row, f"reference is longer than {MAX_REFERENCE_LENGTH} characters"))
    if problems:
        raise _refuse(problems)

    references = raw_references.str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    descriptions = _text_column(frame, columns, "description").str.split().str.join(" ")
    return [
        ParsedRow(row, timestamp.date(), amounts[row], reference, raw_reference, description)
        for row, timestamp, reference, raw_reference, description in zip(
            rows, dates, references, raw_references, descriptions, strict=True
        )
    ]
