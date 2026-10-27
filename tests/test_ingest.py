import datetime as dt
from decimal import Decimal

import pytest

from app.errors import InvalidFile
from app.ingest import MAX_ERRORS_SHOWN, ParsedRow, parse_amount, read_statement


def csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


def problems(content: bytes) -> InvalidFile:
    with pytest.raises(InvalidFile) as caught:
        read_statement(content)
    return caught.value


def test_reads_a_statement_into_normalised_rows() -> None:
    rows = read_statement(
        csv(
            "date,amount,reference,description",
            "2026-10-01,5000.00,INV-1001,NEFT  ACME   TRADERS",
            "2026-10-02,-120.50,,Bank charges",
        )
    )

    assert rows == [
        ParsedRow(
            1, dt.date(2026, 10, 1), Decimal("5000.00"), "INV1001", "INV-1001", "NEFT ACME TRADERS"
        ),
        ParsedRow(2, dt.date(2026, 10, 2), Decimal("-120.50"), "", "", "Bank charges"),
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5000", "5000.00"),
        ("5,000.50", "5000.50"),
        ("1,23,456.78", "123456.78"),  # Indian digit grouping
        ("₹ 2,500", "2500.00"),
        ("INR 2500.5", "2500.50"),
        ("Rs. 99", "99.00"),
        ("+7", "7.00"),
        ("-120.00", "-120.00"),
        ("(120.00)", "-120.00"),
        ("120.00 Dr", "-120.00"),
        ("120.00 CR", "120.00"),
    ],
)
def test_parses_common_amount_formats(text: str, expected: str) -> None:
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("abc", "amount 'abc' is not a number"),
        ("1e5", "amount '1e5' is not a number"),
        ("NaN", "amount 'NaN' is not a number"),
        ("1.2.3", "amount '1.2.3' is not a number"),
        ("12.345", "amount '12.345' has more than two decimal places"),
        ("(-5)", "amount '(-5)' has more than one sign"),
        ("-5 Dr", "amount '-5 Dr' has more than one sign"),
        ("", "amount is missing"),
        ("0.00", "amount is zero"),
    ],
)
def test_refuses_anything_else_with_a_reason(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
        parse_amount(text)


@pytest.mark.parametrize(
    "text", ["2026-10-01", "01/10/2026", "01-10-2026", "01.10.2026", "01-Oct-2026", "01 Oct 2026"]
)
def test_reads_dates_day_first_in_common_formats(text: str) -> None:
    [row] = read_statement(csv("date,amount", f"{text},10"))

    assert row.date == dt.date(2026, 10, 1)


def test_a_two_digit_year_is_read_as_this_century() -> None:
    [row] = read_statement(csv("date,amount", "01/10/26,10"))

    assert row.date == dt.date(2026, 10, 1)


def test_references_are_normalised_and_the_original_is_kept() -> None:
    [row] = read_statement(csv("date,amount,reference", "2026-10-01,10, inv/2026-0042 "))

    assert (row.reference, row.raw_reference) == ("INV20260042", "inv/2026-0042")


def test_debit_and_credit_columns_become_one_signed_amount() -> None:
    rows = read_statement(
        csv(
            "Txn Date,Narration,Ref No./Cheque No.,Debit,Credit",
            '01/10/2026,RENT OCTOBER,CHQ004512,"25,000.00",',
            "02/10/2026,NEFT ACME,UTR9001,,1500.00",
        )
    )

    assert [(row.amount, row.reference) for row in rows] == [
        (Decimal("-25000.00"), "CHQ004512"),
        (Decimal("1500.00"), "UTR9001"),
    ]


def test_the_first_matching_header_wins_when_two_columns_could_be_the_date() -> None:
    [row] = read_statement(csv("Value Date,Date,Amount", "05/10/2026,01/10/2026,10"))

    assert row.date == dt.date(2026, 10, 1)


def test_blank_lines_and_empty_rows_are_skipped() -> None:
    rows = read_statement(csv("date,amount", "2026-10-01,10", "", ",", "2026-10-02,20"))

    assert [(row.row, row.amount) for row in rows] == [(1, Decimal("10.00")), (3, Decimal("20.00"))]


def test_a_byte_order_mark_is_ignored() -> None:
    [row] = read_statement("﻿date,amount\n2026-10-01,10\n".encode())

    assert row.amount == Decimal("10.00")


def test_every_problem_is_reported_with_its_row() -> None:
    error = problems(
        csv(
            "date,amount,reference",
            "2026-10-01,10,A",
            "31/02/2026,10,B",
            "2026-10-03,abc,C",
            "2026-10-04,0,D",
            f"2026-10-05,10,{'R' * 65}",
        )
    )

    assert error.message == "4 rows have problems, so nothing was stored."
    assert error.errors == [
        "row 2: date '31/02/2026' is not a date in a supported format",
        "row 3: amount 'abc' is not a number",
        "row 4: amount is zero",
        "row 5: reference is longer than 64 characters",
    ]


def test_a_single_problem_reads_as_one_row() -> None:
    assert problems(csv("date,amount", "2026-10-01,ten")).message == (
        "1 row has problems, so nothing was stored."
    )


def test_only_the_first_problems_are_listed() -> None:
    error = problems(csv("date,amount", *["someday,10"] * (MAX_ERRORS_SHOWN + 5)))

    assert error.message == f"{MAX_ERRORS_SHOWN + 5} rows have problems, so nothing was stored."
    assert len(error.errors) == MAX_ERRORS_SHOWN


@pytest.mark.parametrize(
    ("debit", "credit", "message"),
    [
        ("100.00", "100.00", "row 1: has both a debit and a credit"),
        ("", "", "row 1: amount is missing"),
        ("-100.00", "", "row 1: debit must not be negative"),
    ],
)
def test_a_debit_and_credit_row_needs_exactly_one_positive_side(
    debit: str, credit: str, message: str
) -> None:
    error = problems(csv("date,debit,credit", f"2026-10-01,{debit},{credit}"))

    assert error.errors == [message]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "The file is empty."),
        (csv("date,amount"), "The file has no rows."),
        (csv("amount,reference", "10,A"), "No date column: name one of date, txn_date,"),
        (csv("date,reference", "2026-10-01,A"), "No amount column: name one amount column,"),
        (csv("date,debit", "2026-10-01,10"), "No amount column: name one amount column,"),
        ("date,amount\n2026-10-01,10\n".encode("utf-16"), "The file is not UTF-8 text."),
        (b'date,amount\n2026-10-01,"10\n', "The file is not valid CSV"),
    ],
)
def test_a_file_that_cannot_be_read_is_refused(content: bytes, message: str) -> None:
    assert problems(content).message.startswith(message)
