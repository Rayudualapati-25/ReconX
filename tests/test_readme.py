"""The README's measured numbers must match the code they describe."""

import re
from pathlib import Path

from app.cli import SAMPLE_SEED, SAMPLE_TRANSACTIONS
from app.config import Settings
from app.demo import generate
from app.domain.reconcile import reconcile
from app.main import create_app
from app.models import Base

README = (Path(__file__).resolve().parents[1] / "README.md").read_text()


def reported(label: str) -> str:
    match = re.search(rf"^\| {label} \| ([^|]+) \|", README, re.MULTILINE)
    assert match, f"the README has no '{label}' row"
    return match.group(1).strip()


def test_the_endpoint_count_matches_the_openapi_schema(settings: Settings) -> None:
    paths = create_app(settings).openapi()["paths"]

    assert reported("Endpoints") == str(sum(len(operations) for operations in paths.values()))


def test_the_table_count_matches_the_models() -> None:
    assert reported("Tables") == str(len(Base.metadata.tables))


def test_the_seeded_numbers_match_a_reconciliation_of_the_samples() -> None:
    data = generate(SAMPLE_TRANSACTIONS, seed=SAMPLE_SEED)
    result = reconcile(data.entries(data.bank), data.entries(data.ledger, first_id=1_000_000))
    score = data.score(result)

    assert reported("Match rate on the seeded data").startswith(f"{result.match_rate:.2%}")
    assert reported("Precision on the seeded data").startswith(f"{score.precision:.2%}")
    assert reported("Recall on the seeded data").startswith(f"{score.recall:.2%}")
