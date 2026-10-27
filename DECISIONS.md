# Design decisions

One entry per decision: what was chosen, the main alternative, why, and what would change
with hindsight. Entries are added in the pull request that makes the decision and revised
when later work proves them right or wrong.

## Service and tooling

### D1. Synchronous SQLAlchemy 2 behind FastAPI

- **Decision.** Path operations are plain `def` functions that use synchronous SQLAlchemy 2
  sessions over psycopg 3. FastAPI runs them in its thread pool.
- **Alternative.** `async def` endpoints with SQLAlchemy's asyncio extension and asyncpg.
- **Why.** The expensive part of ReconX is matching, which is CPU-bound Python; async helps a
  request that waits on I/O, not one that computes. A reconciliation run is a few large
  queries (read both files, bulk-write the results) around an in-memory match, so async would
  add complexity (no lazy loads, no blocking calls on the event loop) for no gain.
- **With hindsight.** No change so far.

### D2. Application factory with injected settings

- **Decision.** `create_app(settings)` builds the app, its engine and its session factory.
  Uvicorn starts it with `--factory`; tests pass their own `Settings`.
- **Alternative.** A module-level `app` and engine configured from environment variables at
  import time.
- **Why.** Tests build an app pointed at the test database without patching environment
  variables, and importing a module has no side effects.
- **With hindsight.** No change so far.

### D3. Tests run against real PostgreSQL, not SQLite

- **Decision.** The suite needs a PostgreSQL 16 database (`TEST_DATABASE_URL`); CI starts one
  as a service container. Each test runs inside a transaction that is rolled back.
- **Alternative.** In-memory SQLite, which needs no setup.
- **Why.** Money is `NUMERIC` and must round-trip exactly, invariants are CHECK constraints,
  and the results are written with PostgreSQL bulk inserts. A suite on SQLite could pass while
  the production database refuses the same rows.
- **With hindsight.** No change so far.

### D4. uv with a committed lockfile

- **Decision.** Dependencies are declared in `pyproject.toml` and pinned in `uv.lock`. CI and
  the Docker build install with `uv sync --locked`, which fails if the lockfile is stale.
- **Alternative.** `pip` with a hand-maintained `requirements.txt`, or pip-tools.
- **Why.** One tool creates the virtualenv, resolves and locks, so CI, Docker and laptops
  install identical versions.
- **With hindsight.** No change so far.

### D5. Quality gates in CI: Ruff, mypy (strict) and an 80% branch-coverage floor

- **Decision.** Every push runs `ruff check`, `ruff format --check`, `mypy` in strict mode
  and `pytest` with branch coverage; coverage below 80% fails the build. Warnings are errors
  in tests, so deprecations surface immediately.
- **Alternative.** flake8 + black + isort, and coverage reported but not enforced.
- **Why.** Ruff replaces three tools with one fast one. A failing gate stops regressions; a
  number in a report only describes them.
- **With hindsight.** No change so far.

### D6. One health endpoint that checks the database

- **Decision.** `GET /health` runs `SELECT 1` and returns 503 when the database is
  unreachable. The Compose healthcheck and the CI smoke test call it.
- **Alternative.** Separate liveness (process is up) and readiness (dependencies are up)
  endpoints.
- **Why.** Docker Compose has one healthcheck per service, so one endpoint is enough.
- **With hindsight.** Under Kubernetes this should be split: restarting the API because the
  database is down does not fix the database.

### D7. Two-stage Docker image running as a non-root user

- **Decision.** A build stage installs the locked dependencies into a virtualenv with uv; the
  runtime stage copies only that virtualenv and the code, and runs as an unprivileged user.
- **Alternative.** A single stage that keeps uv in the final image.
- **Why.** The runtime image carries no build tooling, and a compromised process does not run
  as root.
- **With hindsight.** No change so far.

## Matching

### D8. Three passes, strongest evidence first; each pass sees only the leftovers

- **Decision.** Exact reference through hash maps, then fuzzy reference by bounded edit
  distance, then amount and date by sorting and walking two pointers. Each pass takes only
  what the passes before it left, and every match records the rule that made it. The plan in
  the README numbers the fuzzy pass third; it runs second, for the reason in D10.
- **Alternative.** Score every candidate pair (reference similarity, amount, date gap) and
  solve one global assignment, for example with the Hungarian algorithm.
- **Why.** Most payments carry a usable reference, so the linear pass settles the bulk and the
  costlier comparisons run on the few percent left. A rule name ("same reference") is easier
  for a reviewer to check than a score of 0.83. A global assignment is O(n³), which rules it
  out at 100,000 rows.
- **With hindsight.** No change so far.

### D9. A shared reference pairs entries even when the amount or date disagrees

- **Decision.** The same reference and amount is a match whatever the dates. The same
  reference with a different amount is an amount-mismatch break that links both entries.
  Equal amounts pair first, so a mismatch never takes the partner of an exact match. When a
  reference repeats (rent, a subscription), the nearest dates pair first and ties go to the
  earliest rows: entries are bucketed by date, and a heap of neighbouring bank and ledger
  buckets yields each next-nearest pair, so a reference repeated 20,000 times still pairs in
  O(n log n).
- **Alternative.** Require the date window for reference matches too, or give each entry, in
  file order, its nearest candidate.
- **Why.** A payment reference identifies a payment better than its date does: bookings can
  lag the bank by weeks. Sending a short payment on to the amount pass would let another
  payment of the same amount claim it, turning one explainable mismatch into two misleading
  breaks.
- **With hindsight.** The first version paired in file order. A code review found that rent
  paid on days 1, 31 and 61 against one booking on day 61 matched the day-1 payment and
  reported the real one missing. Pairing is now nearest-first, and a property test checks the
  heap against a brute-force search on generated groups.

### D10. References first: different references never pair on amount alone

- **Decision.** The amount-and-date pass pairs only where at least one side has no reference,
  and it runs after the fuzzy pass. Two entries with different references pair only if they
  are a typo apart, and an entry with no reference cannot take the partner of one with a typo.
- **Alternative.** Pair equal amounts in the window whatever the references say, or run the
  amount pass before the fuzzy pass, as the plan's numbering suggests.
- **Why.** In reconciliation a wrong automatic match costs more than an extra exception: it
  hides a real break where nobody looks. Round amounts (rent, salaries, EMIs) repeat, so
  "same amount, same week" is weak evidence once the references disagree, and a reference one
  keystroke away is stronger evidence than a blank one.
- **With hindsight.** The first version ran the amount pass second. A code review found a
  bank entry with no reference taking ledger `INV20261074` from bank `INV20261047`. With the
  fuzzy pass first, that case pairs correctly; on 5,000 synthetic transactions precision stayed
  at 100% and recall rose from 99.50% to 99.61%.

### D11. Pass 2 pairs only entries that are each other's only candidate

- **Decision.** A bank and a ledger entry pair on amount and date only when each is the
  other's only candidate: the same amount, dates within the window, and at least one of them
  without a reference. When several entries could pair, none is paired, and each becomes a
  break whose reason names the candidates. Both sides are sorted by (amount, date) and two
  pointers mark each entry's window, with prefix counts of unreferenced entries, so one linear
  walk after the sort counts every entry's candidates.
- **Alternative.** Pair greedily in date order within each amount, which pairs as many
  entries as the window allows.
- **Why.** Among equal amounts in the same week (rent, salaries, EMIs) there is nothing to
  choose between candidates, so a greedy pairing is a guess. On 100,000 synthetic transactions
  with known answers, greedy pairing made 559 wrong matches (99.39% precision), all on round
  amounts; pairing only sole candidates made none (100%), and recall rose from 99.17% to
  99.32% because the wrong pairs had been taking the partners of right ones. The match rate
  fell from 94.21% to 93.77%. Being a candidate is symmetric, so removing such a pair changes
  no other entry's candidates: one walk finds them all and the pass stays O(n log n).
- **With hindsight.** The first version paired greedily. Measuring precision against known
  answers, not just the match rate, is what showed the cost, and a property test now checks
  the walk against a brute-force count of candidates.

### D12. Fuzzy references: a bounded edit distance, best pairs first

- **Decision.** Two references are close when they are at most two edits apart and at most
  one edit per five characters of the shorter one, counting an insertion, deletion,
  substitution or swap of neighbouring characters as one edit (the optimal string alignment
  distance). The amount must be equal and the dates within the window. Candidates are found
  by amount and then by bisecting a date-sorted list; every candidate pair is scored (edits,
  then days apart, then rows) and the best pairs are taken first. The distance is computed
  only on a band around the diagonal, stopping as soon as a row exceeds the limit:
  O(limit × length). A property test checks it against the full table.
- **Alternative.** A similarity ratio from a library such as rapidfuzz, or plain Levenshtein
  distance.
- **Why.** A fixed limit treats "AB12" and "AB13", two different payments, like a typo in a
  long reference; scaling by length requires short references to match exactly. A swapped
  pair of digits is the commonest keying error, and Levenshtein would count it twice.
  Requiring the amount and the window stops sequential invoice numbers a month apart from
  matching. The function is 30 lines with no native dependency.
- **With hindsight.** The first version scaled the limit by the longer reference, which let
  "ABCD" match "ABCDE", and gave each bank entry its best candidate in file order, so the
  result depended on row order. The code review caught both.

### D13. A duplicate is an exact repeat on the same side

- **Decision.** An unmatched entry identical to another entry on its own side (date, amount,
  reference and description) is a duplicate of it: of the copy that was paired, or else of
  the first copy, which is reported as missing. Copies present on both sides pair one to one.
- **Alternative.** Flag any two entries with the same reference and amount within the window
  as possible duplicates.
- **Why.** A file loaded twice, or an entry posted twice, produces exact copies, and requiring
  every field to agree keeps the label honest. Two genuine identical payments appear on both
  sides and simply match.
- **With hindsight.** A bank that re-presents a payment a day later produces a near-copy,
  which is reported as missing rather than as a duplicate. It is still a break, but with a
  less helpful label.

### D14. The match rate counts entries on both sides

- **Decision.** Match rate = 2 × matched pairs / (bank entries + ledger entries). Amount
  mismatches pair two entries but count as breaks, not matches.
- **Alternative.** Matched bank entries over bank entries.
- **Why.** A ledger entry missing from the bank is as much a break as the reverse; a rate
  over one side would hide it.
- **With hindsight.** No change so far.

### D15. The engine is pure functions, checked by properties

- **Decision.** `app/domain` has no database or HTTP code. Entries are frozen dataclasses and
  `reconcile(bank, ledger, config)` returns the matches and breaks, sorting its input by row
  first so the caller's order never matters. Hypothesis checks, on generated files: every
  entry lands in exactly one match or break; every match has the evidence its rule names; no
  two unmatched entries could still pair on a reference; the amount pass pairs exactly the
  sole candidates and nearest-first pairing takes the nearest remaining pair, both against
  brute-force versions; and shuffling the input changes nothing.
- **Alternative.** Match inside the service layer on ORM objects, or in SQL with joins.
- **Why.** Pure code is unit-tested in milliseconds, and the same function serves the API,
  the benchmark and the comparison with the naive matcher. The properties have teeth: a pass
  without the reference guard, a pass that pairs nothing, a window off by one and a dropped
  break each make one of them fail.
- **With hindsight.** The first property tests missed what the code review found (order
  dependence, file-order pairing), because none of them compared the engine with a slower,
  obviously correct version. The brute-force comparisons and the shuffle test close that gap.

### D16. Worst-case inputs stay fast

- **Decision.** Every pass stays O(n log n) however the keys repeat, explanations bisect into
  date-sorted lists instead of scanning, and a reference with more than 100 same-amount
  lookalikes in its window is not fuzzy-matched. Configured windows are limited to 365 days
  and edit limits to 5. A test reconciles 20,000 entries a side that share one reference, one
  amount, or one day, in well under five seconds.
- **Alternative.** Trust that real statements have near-unique references.
- **Why.** An upload is untrusted input: a crafted file whose rows all share a reference made
  the first version quadratic (eight minutes at 100,000 rows, by the review's estimate), which
  is enough to pin an API worker.
- **With hindsight.** No change so far.

