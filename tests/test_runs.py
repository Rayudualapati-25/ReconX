"""Runs end to end through the API: upload two files, reconcile, review and resolve breaks.

The two files below are built so that every rule and every break type appears once.
"""

from typing import Any
from unittest.mock import ANY

import pytest
from fastapi.testclient import TestClient

STATEMENT = b"""date,amount,reference,description
2026-10-01,5000.00,INV-1001,NEFT CR ACME
2026-10-02,4985.00,INV-1002,NEFT CR GLOBEX
2026-10-03,1200.00,,CASH DEPOSIT
2026-10-04,18250.00,INV20261047,RTGS CR INITECH
2026-10-05,-350.00,,BANK CHARGES
2026-10-01,5000.00,INV-1001,NEFT CR ACME
"""
LEDGER = b"""date,reference,description,amount
2026-10-01,INV-1001,Receipt from Acme,5000.00
2026-10-02,INV-1002,Receipt from Globex,5000.00
2026-10-02,RCPT-77,Cash receipt,1200.00
2026-10-03,INV20261074,Receipt from Initech,18250.00
2026-10-06,CHQ-0042,Payment to Stark,-9999.00
"""


def upload(client: TestClient, kind: str, content: bytes) -> int:
    response = client.post(f"/uploads/{kind}", files={"file": (f"{kind}.csv", content)})
    assert response.status_code in (200, 201), response.text
    upload_id: int = response.json()["id"]
    return upload_id


def start(client: TestClient, **settings: Any) -> dict[str, Any]:
    body = {
        "bank_upload_id": upload(client, "bank", STATEMENT),
        "ledger_upload_id": upload(client, "ledger", LEDGER),
    }
    response = client.post("/runs", json=body | settings)
    assert response.status_code == 201, response.text
    run: dict[str, Any] = response.json()
    return run


def breaks(client: TestClient, run_id: int, **params: Any) -> dict[str, Any]:
    response = client.get(f"/runs/{run_id}/breaks", params=params)
    assert response.status_code == 200, response.text
    page: dict[str, Any] = response.json()
    return page


def test_a_run_matches_what_it_can_and_counts_what_it_cannot(client: TestClient) -> None:
    run = start(client)

    assert run == {
        "id": ANY,
        "created_at": ANY,
        "bank_upload": ANY,
        "ledger_upload": ANY,
        "date_window_days": 3,
        "max_edits": 2,
        "bank_count": 6,
        "ledger_count": 5,
        "matched_count": 3,
        "match_rate": 0.5455,
        "duration_ms": ANY,
        "matches_by_rule": {"exact_reference": 1, "fuzzy_reference": 1, "amount_date": 1},
        "breaks_by_type": [
            {"type": "missing_in_bank", "open": 1, "resolved": 0, "open_amount": "9999.00"},
            {"type": "missing_in_ledger", "open": 1, "resolved": 0, "open_amount": "350.00"},
            {"type": "amount_mismatch", "open": 1, "resolved": 0, "open_amount": "15.00"},
            {"type": "duplicate", "open": 1, "resolved": 0, "open_amount": "5000.00"},
        ],
        "open_breaks": 4,
        "open_amount": "15364.00",
    }
    assert run["bank_upload"]["kind"] == "bank"
    assert run["ledger_upload"]["filename"] == "ledger.csv"


def test_breaks_come_largest_first_with_the_entries_they_are_about(client: TestClient) -> None:
    run = start(client)

    page = breaks(client, run["id"])

    assert page["total"] == 4
    assert [item["type"] for item in page["items"]] == [
        "missing_in_bank",
        "duplicate",
        "missing_in_ledger",
        "amount_mismatch",
    ]
    mismatch = page["items"][3]
    assert mismatch | {"id": 0} == {
        "id": 0,
        "run_id": run["id"],
        "type": "amount_mismatch",
        "status": "open",
        "reason": (
            "Same reference INV1002, but the bank shows 4,985.00 and the ledger 5,000.00: "
            "the bank is 15.00 lower."
        ),
        "amount": "15.00",
        "difference": "-15.00",
        "bank": {
            "id": ANY,
            "row": 2,
            "date": "2026-10-02",
            "amount": "4985.00",
            "reference": "INV-1002",
            "description": "NEFT CR GLOBEX",
        },
        "ledger": {
            "id": ANY,
            "row": 2,
            "date": "2026-10-02",
            "amount": "5000.00",
            "reference": "INV-1002",
            "description": "Receipt from Globex",
        },
        "resolution_note": None,
        "resolved_at": None,
    }
    assert page["items"][1]["reason"] == (
        "Repeats bank row 1: same date, amount, reference and description."
    )


def test_breaks_filter_by_type_and_status_and_come_in_pages(client: TestClient) -> None:
    run_id = start(client)["id"]

    assert [b["type"] for b in breaks(client, run_id, type="duplicate")["items"]] == ["duplicate"]
    assert breaks(client, run_id, status="resolved")["total"] == 0
    page = breaks(client, run_id, limit=2, offset=1)
    assert (page["total"], page["limit"], page["offset"]) == (4, 2, 1)
    assert [b["type"] for b in page["items"]] == ["duplicate", "missing_in_ledger"]


def test_resolving_a_break_records_the_note_and_updates_the_summary(client: TestClient) -> None:
    run_id = start(client)["id"]
    mismatch = breaks(client, run_id, type="amount_mismatch")["items"][0]

    response = client.post(
        f"/breaks/{mismatch['id']}/resolve", json={"note": "  Bank charges, booked to fees  "}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    assert response.json()["resolution_note"] == "Bank charges, booked to fees"
    assert response.json()["resolved_at"] is not None
    summary = client.get(f"/runs/{run_id}").json()
    assert summary["open_breaks"] == 3
    assert summary["open_amount"] == "15349.00"
    assert summary["breaks_by_type"][2] == {
        "type": "amount_mismatch",
        "open": 0,
        "resolved": 1,
        "open_amount": "0.00",
    }
    assert breaks(client, run_id, status="open")["total"] == 3


def test_a_resolved_break_cannot_be_resolved_again(client: TestClient) -> None:
    run_id = start(client)["id"]
    break_id = breaks(client, run_id)["items"][0]["id"]
    client.post(f"/breaks/{break_id}/resolve", json={"note": "Cheque not yet presented"})

    again = client.post(f"/breaks/{break_id}/resolve", json={"note": "Again"})

    assert again.status_code == 409
    assert again.json()["code"] == "break_already_resolved"


@pytest.mark.parametrize("note", ["", "   ", "x" * 501])
def test_resolving_needs_a_short_note(client: TestClient, note: str) -> None:
    run_id = start(client)["id"]
    break_id = breaks(client, run_id)["items"][0]["id"]

    assert client.post(f"/breaks/{break_id}/resolve", json={"note": note}).status_code == 422


def test_the_same_files_can_be_reconciled_again_with_other_settings(client: TestClient) -> None:
    default = start(client)
    strict = start(client, date_window_days=0)

    # With no window, the cash deposit a day after its receipt is no longer paired.
    assert strict["id"] != default["id"]
    assert strict["matches_by_rule"] == {
        "exact_reference": 1,
        "fuzzy_reference": 0,
        "amount_date": 0,
    }
    assert [run["id"] for run in client.get("/runs").json()] == [strict["id"], default["id"]]


@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        ({"bank_upload_id": 999_999}, 404, "upload_not_found"),
        ({"swap": True}, 422, "wrong_upload_kind"),
    ],
)
def test_a_run_needs_a_bank_upload_and_a_ledger_upload(
    client: TestClient, change: dict[str, Any], status: int, code: str
) -> None:
    bank_id, ledger_id = upload(client, "bank", STATEMENT), upload(client, "ledger", LEDGER)
    body = {"bank_upload_id": bank_id, "ledger_upload_id": ledger_id}
    if change.pop("swap", False):
        body = {"bank_upload_id": ledger_id, "ledger_upload_id": bank_id}

    response = client.post("/runs", json=body | change)

    assert (response.status_code, response.json()["code"]) == (status, code)


def test_the_wrong_kind_of_upload_is_named(client: TestClient) -> None:
    ledger_id = upload(client, "ledger", LEDGER)

    response = client.post(
        "/runs", json={"bank_upload_id": ledger_id, "ledger_upload_id": ledger_id}
    )

    assert response.json()["detail"] == f"Upload {ledger_id} is a ledger, not a bank statement."


@pytest.mark.parametrize(
    "invalid", [{"date_window_days": 31}, {"max_edits": 4}, {"date_window_days": -1}, {"x": 1}]
)
def test_run_settings_are_checked(client: TestClient, invalid: dict[str, int]) -> None:
    body = {"bank_upload_id": 1, "ledger_upload_id": 2} | invalid

    assert client.post("/runs", json=body).status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "code"),
    [
        ("get", "/runs/999999", "run_not_found"),
        ("get", "/runs/999999/breaks", "run_not_found"),
        ("post", "/breaks/999999/resolve", "break_not_found"),
    ],
)
def test_unknown_runs_and_breaks_are_404(
    client: TestClient, method: str, path: str, code: str
) -> None:
    response = client.request(method, path, json={"note": "n/a"})

    assert (response.status_code, response.json()["code"]) == (404, code)
