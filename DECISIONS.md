# Design decisions

One entry per decision: what was chosen, the main alternative, why, and what would change
with hindsight. Entries are added in the pull request that makes the decision and revised
when later work proves them right or wrong.

Contents: [Service and tooling](#service-and-tooling) (D1–D7) · [Matching](#matching)
(D8–D16) · [Ingest and storage](#ingest-and-storage) (D17–D22) ·
[Runs and review](#runs-and-review) (D23–D27) ·
[Benchmark and demo data](#benchmark-and-demo-data) (D28–D31) · [Dashboard](#dashboard)
(D32–D35)

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

## Ingest and storage

### D17. pandas reads every cell as text; amounts go straight to Decimal

- **Decision.** `read_csv(dtype=str, keep_default_na=False)`. Each amount is parsed by a small
  grammar (an optional ₹, INR or Rs prefix; Indian or Western digit grouping; `-`, `(…)` or
  `Dr` for money out) into a `Decimal` with at most two places, stored as `NUMERIC(14, 2)`.
- **Alternative.** Let pandas infer numeric columns as float64 and round afterwards.
- **Why.** A float64 cannot hold most decimal amounts exactly, and two amounts that should be
  equal can then compare unequal, which breaks matching. Text in, Decimal out keeps amounts
  exact from the file to the database. `keep_default_na=False` also stops pandas turning a
  reference such as `NA` or `NULL` into a missing value.
- **With hindsight.** No change so far.

### D18. A file with any bad row is refused whole, with every problem listed

- **Decision.** Problems are collected row by row (date, amount, debit and credit, reference
  length) and returned as a 422 listing up to 20 of them, such as "row 3: amount 'ten' is not a
  number". Nothing is stored.
- **Alternative.** Store the valid rows and report the others.
- **Why.** A dropped row reappears later as a false "missing in bank" break, far from its
  cause. Listing every problem lets the uploader fix the file in one go.
- **With hindsight.** Exports that mix in non-transaction lines (page footers, running totals)
  would be better served by an explicit option to skip them than by editing the file.

### D19. Dates are read day first; columns are found by common header names

- **Decision.** A fixed list of date formats is tried in order: ISO first, then `DD/MM/YYYY`
  and its variants; a two-digit year is 20xx. Headers are matched loosely ("Txn Date",
  "Ref No./Cheque No.", "Withdrawal Amt.") against alias lists, and separate debit and credit
  columns become one signed amount.
- **Alternative.** pandas' format inference with `dayfirst=True`, or a column mapping that the
  uploader configures for each file.
- **Why.** Indian statements write `01/02/2026` for 1 February, and inference can silently
  flip day and month when a value could be either. Explicit formats fail loudly instead. The
  alias lists cover the usual exports with no configuration.
- **With hindsight.** A column mapping saved per bank account would handle unusual layouts
  without a code change.

### D20. The same file is stored once, by content hash

- **Decision.** Each upload records the SHA-256 of its bytes, unique per kind. Uploading the
  same bytes again returns the stored upload with 200 instead of 201. Two identical uploads at
  the same moment are settled by `INSERT … ON CONFLICT DO NOTHING`; a test commits the same
  file from a second connection in the middle of an upload and checks the outcome.
- **Alternative.** Store every upload, or deduplicate individual rows.
- **Why.** Loading the same statement twice is a classic source of false duplicates. Hashing
  the bytes catches the exact case cheaply and without any judgement about rows.
- **With hindsight.** A re-export of the same statement with one edit has different bytes and
  is stored again. Detecting overlapping date ranges for the same account would catch it.

### D21. Entries are written with COPY

- **Decision.** Rows are streamed with PostgreSQL's `COPY … FROM STDIN` through psycopg 3,
  inside the same transaction as the upload row.
- **Alternative.** ORM objects, or SQLAlchemy's batched `INSERT … VALUES`.
- **Why.** Measured on the development machine: 100,000 entries take 0.75 s with COPY against
  2.2 s with batched INSERTs. Runs write as many matches and breaks again, so the saving
  repeats. COPY still runs inside the transaction, so a failure leaves nothing behind.
- **With hindsight.** No change so far.

### D22. References are stored twice: normalised, and as written

- **Decision.** `reference` (upper case, letters and digits only, enforced by a CHECK
  constraint) is what matching compares; `raw_reference` is what the file said, and is what
  reviewers see.
- **Alternative.** Store only the normalised form.
- **Why.** "INV/2026-0042" and "inv 2026 0042" must compare equal, but a reviewer searches the
  original statement for what it actually printed.
- **With hindsight.** No change so far.

## Runs and review

### D23. A run is computed in the request and stored in full

- **Decision.** `POST /runs` loads both uploads, reconciles them in memory, writes every match
  and break with COPY, and returns the summary in the same request. Runs never change; running
  the same uploads with other settings makes a new run.
- **Alternative.** A job queue (Celery or RQ) with a status endpoint to poll, or matching on
  the fly whenever results are read.
- **Why.** Matching 100,000 rows a side takes about a second, so a queue would add a broker, a
  worker and a status machine with nothing to show for them. Stored results make the
  exception queue a cheap indexed query, and keep a record of what each run decided.
- **With hindsight.** No change so far. Past a few million rows, or with many uploads at once,
  the run would move to a worker and the request would return its id.

### D24. Resolving a break is one conditional UPDATE

- **Decision.** `POST /breaks/{id}/resolve` runs `UPDATE … WHERE id = :id AND status = 'open'
  RETURNING id`. No row back means 404 (no such break) or 409 (already resolved). A note is
  required, and a CHECK constraint makes every resolved break carry a note and a time.
- **Alternative.** Load the break, check its status in Python, then save it, which needs a
  row lock to be safe; or optimistic version numbers.
- **Why.** The check and the change happen in one statement, so two reviewers resolving the
  same break at once cannot both succeed, and no lock is held while anyone thinks.
- **With hindsight.** No change so far. A real team would record who resolved each break
  (which needs sign-in) and a category (bank charges, timing difference, posting error) to
  report on.

### D25. A break stores the money it puts in doubt

- **Decision.** Each break stores `amount`: the difference for an amount mismatch, otherwise
  the entry's amount, always positive. The summary sums the open amounts by type, and the
  exception queue lists the largest first.
- **Alternative.** Work it out at read time by joining the entries.
- **Why.** Reviewers clear the biggest problems first, and "₹15,364.00 to review" says more
  than "4 breaks". Stored, it keeps the summary to one GROUP BY over one table.
- **With hindsight.** No change so far.

### D26. Summaries are counted live, not kept as counters

- **Decision.** Matches by rule and open and resolved breaks by type are `GROUP BY` queries
  with `FILTER`, run on every `GET /runs/{id}`. The run row stores only what never changes:
  the settings, entry counts, matched count and matching time.
- **Alternative.** Counters on the run row, updated whenever a break is resolved.
- **Why.** Counters drift as soon as one write path forgets them. The queries use the
  `(run_id, status, type)` index and stay fast at thousands of breaks.
- **With hindsight.** No change so far.

### D27. The exception queue pages by limit and offset and returns the total

- **Decision.** `GET /runs/{id}/breaks?type=&status=&limit=&offset=` returns
  `{items, total, limit, offset}`, each break with both of its entries joined in the same
  query. The run's relationships raise on lazy loading, so an N+1 query fails a test instead
  of slowing a page.
- **Alternative.** Keyset (cursor) pagination.
- **Why.** The dashboard shows "26–50 of 460" and moves a page at a time; queues hold
  thousands of rows, not millions.
- **With hindsight.** Offset pages shift when breaks are resolved mid-way; keyset paging on
  `(amount, id)` would fix that.

## Benchmark and demo data

### D28. The baseline applies the same rules with nested loops

- **Decision.** `naive_reconcile` runs the same passes in the same order, but each pass
  compares every remaining bank entry with every remaining ledger entry, taking each bank
  entry's best candidate in file order: O(n × m), with no hash maps, sorting or bisection. It
  reuses the engine's break explanations, which are not what is being compared. A test checks
  that both find the same matches and breaks on the demo data, and the benchmark checks it
  again at every size.
- **Alternative.** A deliberately crude baseline (exact references only), or an O(n²) time
  extrapolated from a small run.
- **Why.** A speed-up means something only if both sides give the same answers; a crude
  baseline would compare features, not algorithms. Running the baseline at 100,000 rows
  reports a measured time, not a projection.
- **With hindsight.** No change so far.

### D29. Demo data is synthetic, with the answers planted

- **Decision.** `app/demo.py` invents both files from a seeded random generator, with
  fictional counterparties ("Acme Traders", "Globex Supplies"). Each transaction gets a
  scenario: 84% clean, 4% reference missing on one side, 3% a typo, 2% bank charges taken off,
  3% ledger only, 3% bank only, 1% loaded twice. The generator keeps what every row really is,
  and never writes it to the CSVs. 15% of amounts are round figures that recur, as rent and
  retainers do. Only `random()` is drawn, the one sequence Python keeps stable across
  versions, and a test checks that the committed samples are exactly its output.
- **Alternative.** Anonymised real statements, or hand-written fixtures.
- **Why.** Real statements carry personal and financial data, which has no place in a public
  repository. Planted answers turn a match rate into precision and recall, which is how the
  greedy amount pass was caught (D11).
- **With hindsight.** The scenario mix is a guess at a typical business. Real books would
  show which breaks dominate, and cases the generator leaves out: partial payments, and one
  payment settling several invoices.

### D30. The demo seed uploads the committed samples through the real code

- **Decision.** `python -m app.cli seed --if-empty` uploads `samples/bank_statement.csv` and
  `samples/ledger.csv` with the same service as `POST /uploads` and reconciles them as
  `POST /runs` does. Docker Compose runs it on first start (`SEED_DEMO_DATA=true`).
- **Alternative.** SQL fixtures, or rows inserted directly.
- **Why.** The seed is then one more end-to-end test of ingest and reconciliation, and anyone
  can upload the same two files again from the dashboard; they are deduplicated (D20).
- **With hindsight.** No change so far.

### D31. The benchmark times matching only, on in-memory entries

- **Decision.** `scripts/benchmark.py` times `reconcile` (best of three) and `naive_reconcile`
  (one run) on the same entries. CSV parsing and the database are left out; COPY was measured
  on its own (D21). The output records the Python version and machine.
- **Alternative.** Time whole API requests.
- **Why.** The claim under test is algorithmic, O(n) and O(n log n) against O(n²); reading
  files and writing rows add roughly the same cost to both.
- **With hindsight.** No change so far.

## Dashboard

### D32. One page, with no UI or chart library

- **Decision.** React 19 and TypeScript, built with Vite. Plain CSS with custom properties,
  light or dark following the system setting; the charts are CSS bars. No component library,
  chart library or state manager: 72 KB of JavaScript, gzipped.
- **Alternative.** A component library such as Material UI, a chart library such as
  Recharts, and a data-fetching library such as TanStack Query.
- **Why.** The page is five tiles, two bar lists and a table, which a library would outweigh.
  Fewer dependencies mean fewer upgrades and a smaller download, and the fetching is three
  effects that ignore stale responses.
- **With hindsight.** More screens (drilling into matches, comparing runs) would justify
  TanStack Query for caching and refetching.

### D33. The dashboard reaches the API through its own origin

- **Decision.** The browser calls `/api/…`. nginx in the Compose stack, and Vite's dev server
  locally, forward it to the API without the prefix.
- **Alternative.** Call the API's own origin and enable CORS in FastAPI.
- **Why.** One origin means no CORS rules to get wrong, and the same build works wherever the
  proxy runs. nginx also caps request size before an oversized upload reaches the API.
- **With hindsight.** No change so far.

### D34. Money stays a string in the browser too

- **Decision.** The API sends amounts as strings, and the dashboard formats them by splitting
  the digits (Indian grouping, `₹1,23,456.78`). It never parses an amount into a number or
  adds amounts up; totals come from the API.
- **Alternative.** `parseFloat` and `Intl.NumberFormat`.
- **Why.** For the same reason as on the server (D17): a float cannot hold most amounts
  exactly, and a total summed in JavaScript could disagree with the database's.
- **With hindsight.** No change so far.

### D35. Dashboard tests render the whole app against a fake API

- **Decision.** Vitest and Testing Library render `<App>` with an injected `Api` whose methods
  are stubs. Tests click and type as a reviewer would (pick a break type, resolve with a note,
  upload a refused file) and check what is shown and what was called. The Compose smoke test
  checks the real API behind the real proxy.
- **Alternative.** Mock `fetch` globally, or snapshot-test components.
- **Why.** An injected API keeps the tests independent of URLs and of how fetching works, and
  testing behaviour rather than markup leaves the structure and CSS free to change.
- **With hindsight.** Looking at the running page found two layout bugs that these tests
  cannot see: a wide table stretching the whole grid, and a long run label pushing a phone
  screen sideways. A browser test against the Compose stack, with Playwright, is the next
  test to add.
