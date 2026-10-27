"""Bounded edit distance: how many keystrokes apart two references are."""


def edit_distance_within(a: str, b: str, limit: int) -> int | None:
    """The edit distance between `a` and `b` if it is at most `limit`, otherwise None.

    Inserting, deleting or substituting a character, or swapping two adjacent characters,
    costs one edit each (the optimal string alignment distance): a swapped pair of digits is
    the commonest keying error, and plain Levenshtein would count it as two.

    Only cells within `limit` of the diagonal can hold a distance of `limit` or less, so only
    those are computed, and the scan stops as soon as a whole row exceeds the limit. That makes
    it O(limit x length) instead of O(length squared).
    """
    if limit < 0:
        raise ValueError("limit must not be negative")
    if abs(len(a) - len(b)) > limit:
        return None
    if a == b:
        return 0
    too_far = limit + 1
    before_previous: list[int] = []
    previous = [j if j <= limit else too_far for j in range(len(b) + 1)]
    for i in range(1, len(a) + 1):
        current = [too_far] * (len(b) + 1)
        if i <= limit:
            current[0] = i
        row_minimum = current[0]
        for j in range(max(1, i - limit), min(len(b), i + limit) + 1):
            distance = min(
                previous[j] + 1,  # delete a[i - 1]
                current[j - 1] + 1,  # insert b[j - 1]
                previous[j - 1] + (a[i - 1] != b[j - 1]),  # substitute, free if equal
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                distance = min(distance, before_previous[j - 2] + 1)  # swap a neighbour pair
            current[j] = min(distance, too_far)
            row_minimum = min(row_minimum, current[j])
        if row_minimum > limit:
            return None
        before_previous, previous = previous, current
    return previous[len(b)] if previous[len(b)] <= limit else None
