import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.edit_distance import edit_distance_within


def full_table_distance(a: str, b: str) -> int:
    """Optimal string alignment distance from the textbook full table, with no shortcuts."""
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        table[i][0] = i
    for j in range(len(b) + 1):
        table[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            table[i][j] = min(table[i - 1][j] + 1, table[i][j - 1] + 1, table[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                table[i][j] = min(table[i][j], table[i - 2][j - 2] + 1)
    return table[len(a)][len(b)]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("INV1001", "INV1001", 0),
        ("INV1001", "INV1002", 1),  # one wrong digit
        ("INV1001", "INV1010", 1),  # two digits swapped
        ("INV1001", "INV101", 1),  # one digit dropped
        ("INV1001", "INV10012", 1),  # one digit added
        ("INV1001", "INV2002", 2),
        ("", "AB", 2),
    ],
)
def test_counts_common_keying_errors(a: str, b: str, expected: int) -> None:
    assert edit_distance_within(a, b, 2) == expected


def test_returns_none_beyond_the_limit() -> None:
    assert edit_distance_within("ABCDEF", "ABCXYZ", 2) is None


def test_a_length_difference_alone_can_exceed_the_limit() -> None:
    assert edit_distance_within("INV1", "INV1001", 2) is None


def test_a_limit_of_zero_accepts_only_equal_strings() -> None:
    assert edit_distance_within("UTR42", "UTR42", 0) == 0
    assert edit_distance_within("UTR42", "UTR43", 0) is None


def test_a_negative_limit_is_refused() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        edit_distance_within("A", "B", -1)


@given(st.text("AB01", max_size=9), st.text("AB01", max_size=9), st.integers(0, 4))
def test_agrees_with_the_full_table_up_to_the_limit(a: str, b: str, limit: int) -> None:
    expected = full_table_distance(a, b)

    assert edit_distance_within(a, b, limit) == (expected if expected <= limit else None)
