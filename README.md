# ReconX

[![CI](https://github.com/Rayudualapati-25/ReconX/actions/workflows/ci.yml/badge.svg)](https://github.com/Rayudualapati-25/ReconX/actions/workflows/ci.yml)

A payment reconciliation engine. It matches a bank statement against an
internal ledger, flags every break (missing, duplicate or mismatched
payments) and shows the match rate on a dashboard.

Built with FastAPI, PostgreSQL and pandas, with a React + TypeScript
dashboard, test-first.

## Status

MVP complete: every item below is built, tested and running in CI. Measured on this
repository:

| Measure | Value |
|---|---|
| Matching 102,347 bank rows against 102,386 ledger rows | 1.11 s, 184,458 rows/s |
| Naive O(n²) matcher on the same rows | 389 s, 526 rows/s: the engine is 351× faster, same matches |
| Match rate on the seeded data | 94.30% (4,601 pairs from 4,862 bank and 4,896 ledger entries) |
| Precision on the seeded data | 100.00%: no wrong automatic match |
| Recall on the seeded data | 99.61% of the true pairs matched |
| Tests | 176 for the API (99.5% branch coverage), 15 for the dashboard |
| Endpoints | 8 |
| Tables | 5 |

The demo data is synthetic with the true pairs planted (DECISIONS D29), which is what makes
precision and recall measurable. A test checks the seeded figures, endpoints and tables
against the code, so they cannot drift.

## MVP scope

- [x] CSV ingest for the bank statement and the ledger into PostgreSQL,
      normalising amounts (`Decimal`), dates and references
- [x] Pass 1: exact reference match with a hash map, O(n)
- [x] Pass 2: amount and date-window match with sorted two pointers,
      O(n log n)
- [x] Pass 3: fuzzy reference match (edit distance) on the leftovers only
      (it runs before pass 2: a similar reference is stronger evidence than a
      shared amount, see DECISIONS D10)
- [x] Break types with a reason for each: missing in bank, missing in ledger,
      amount mismatch, duplicate
- [x] REST API: upload both files, run a reconciliation, list and resolve
      breaks
- [x] React + TypeScript dashboard: match rate, breaks by type, exception
      queue with manual resolve
- [x] Benchmark against a naive O(n²) matcher on 100k rows, with the numbers
      in this README
- [x] pytest suite with coverage (target 80%+), Docker Compose (API, Postgres,
      dashboard), GitHub Actions CI on every push
- [x] `DECISIONS.md`: each design choice, the alternative considered, and what
      would change with hindsight

## How it works

```
bank.csv ─┐                       ┌─ exact reference ──┐
          ├─ ingest ─ PostgreSQL ─┤  fuzzy reference   ├─ matches + breaks ─ API ─ dashboard
ledger.csv┘  (Decimal, day-first, └─ amount and date ──┘   (with reasons)
              normalised refs)        each pass sees only the leftovers
```

1. **Ingest.** pandas reads both CSVs as text, so amounts go straight to `Decimal`; dates are
   read day first; references are upper-cased and stripped to letters and digits. A file with
   any bad row is refused with every problem listed, and the same file is stored once.
2. **Exact reference**, O(n). Hash maps by reference: the same reference and amount is a
   match; the same reference with another amount is an *amount mismatch*. Within a reference
   that repeats (rent, a subscription), the nearest dates pair first.
3. **Fuzzy reference**, on the leftovers only. References at most two edits apart (a swapped
   digit pair counts once; short references must match exactly), with the same amount and
   dates within 3 days. The best pairs go first.
4. **Amount and date**, O(n log n). Both sides sorted by (amount, date) and walked with two
   pointers. An entry with no reference pairs with the one entry on the other side that has
   the same amount within the window, and only if that entry has no other candidate either.
   Several equal amounts in a week are a guess, so they are left for a person.
5. **Breaks.** Everything left is *missing in bank*, *missing in ledger* or a *duplicate* (an
   exact repeat on one side), each with a reason a reviewer can act on, such as "Ledger rows
   12, 40 have the same amount within 3 days, but more than one entry could pair, so none was
   paired automatically."

Every match records the rule that made it. Two different references never pair on amount
alone: a wrong automatic match hides a real break, which costs more than an extra exception
(DECISIONS D10, D11).

## API

| Method | Path | What |
|---|---|---|
| GET | `/health` | API and database health |
| POST | `/uploads/{bank\|ledger}` | upload a CSV; 201, or 200 if the same file was uploaded before; 422 lists every bad row |
| GET | `/uploads` | uploaded files, newest first |
| POST | `/runs` | reconcile a bank upload against a ledger upload (`date_window_days`, `max_edits`) |
| GET | `/runs` | runs, newest first |
| GET | `/runs/{id}` | match rate, matches by rule, open and resolved breaks by type, money in doubt |
| GET | `/runs/{id}/breaks` | the exception queue: `?type=&status=&limit=&offset=`, largest amount first |
| POST | `/breaks/{id}/resolve` | resolve with a note; 409 if already resolved |

Errors share one shape, `{"detail": "...", "code": "...", "errors": [...]}`. Money is sent as
strings (`"5000.00"`). The full schema is at `/docs` on a running stack.

## Input files

CSV, UTF-8, one header row. Columns are found by common names, case and punctuation ignored:

| Field | Header names accepted |
|---|---|
| Date (required) | `date`, `txn date`, `transaction date`, `posting date`, `value date`, … |
| Amount (required) | `amount`, or a `debit` / `withdrawal` column with a `credit` / `deposit` column |
| Reference | `reference`, `ref no.`, `utr`, `cheque no.`, `ref no./cheque no.`, … |
| Description | `description`, `narration`, `particulars`, `memo`, `remarks`, … |

Dates are day first (`01/10/2026` is 1 October); amounts may use Indian or Western digit
grouping, a ₹, INR or Rs prefix, and `-`, `(…)` or `Dr` for money out. Money in is positive on
both files.

## Quick start

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| Dashboard | <http://localhost:3000> |
| API and interactive docs | <http://localhost:8000/docs> |

![The dashboard: match rate, open breaks by type with the money in doubt, matches by rule, and the exception queue](docs/dashboard.jpg)

On first start the API container migrates the database, uploads the two sample files in
[`samples/`](samples) through the same code as `POST /uploads`, and reconciles them, so the
dashboard opens on a finished run: the match rate, open breaks by type with the money in
doubt, matches by rule, and the exception queue. Pick a break type to filter the queue, and
**Resolve** a break with a note. **New reconciliation** uploads two other CSV files.

The sample files are synthetic (DECISIONS D29): fictional counterparties, invented references
and amounts, nothing real. `python3 scripts/smoke_test.py` checks a running stack end to end.

## Benchmark

The engine against a naive matcher that applies the same rules with nested loops, comparing
every bank entry with every ledger entry (DECISIONS D28). Both run on the same synthetic
statements, whose true pairs are known (D29), so the table also reports precision and recall.
Only matching is timed: no CSV parsing and no database (D31).

| Bank rows | Ledger rows | Engine | Engine rows/s | Naive O(n²) | Naive rows/s | Speed-up | Same matches | Precision | Recall | Match rate |
|---|---|---|---|---|---|---|---|---|---|---|
| 1,036 | 1,054 | 0.003 s | 734,579 | 0.04 s | 51,656 | 14x | yes | 100.00% | 99.90% | 94.26% |
| 10,254 | 10,283 | 0.041 s | 499,078 | 3.77 s | 5,448 | 92x | yes | 100.00% | 99.43% | 93.94% |
| 102,347 | 102,386 | 1.110 s | 184,458 | 389.24 s | 526 | 351x | yes | 100.00% | 99.33% | 93.77% |

Rows per second count both files. "Same matches" means the naive matcher found exactly the
pairs the engine found. Measured with `uv run python scripts/benchmark.py` on an Apple silicon
laptop (arm64, Python 3.12.16, one core). The naive run at 100,000 rows takes about six and a
half minutes; pass `--naive-max 10000` for a quick run.

End to end through the services behind the API, on a local PostgreSQL 16 container, the
100,000-row files took 3.89 s to parse and store, then 4.70 s to reconcile and store the 95,988
matches and every break, of which matching was 1.37 s. Pass `--database-url` (an empty,
migrated database) to reproduce it.

## Stack

Python 3.11+ · FastAPI · PostgreSQL 16 · SQLAlchemy 2 · Alembic · pandas · Pydantic v2 ·
React 19 · TypeScript · Vite · pytest · Hypothesis · Vitest · Docker Compose · GitHub Actions

## Development

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and PostgreSQL 16 for the tests.

```bash
uv sync                                   # virtualenv with runtime and dev dependencies
docker run -d --name reconx-test-db -p 5432:5432 \
  -e POSTGRES_USER=reconx -e POSTGRES_PASSWORD=reconx \
  -e POSTGRES_DB=reconx_test postgres:16-alpine
uv run pytest --cov                       # tests with branch coverage (80% floor)
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

The dashboard needs Node 22:

```bash
cd dashboard && npm ci
npm run dev                               # http://localhost:5173, /api forwarded to :8000
npm test && npm run lint && npm run build
```

The tests use `TEST_DATABASE_URL` (see `.env.example`) and default to the container above.

```
app/
  domain/      the engine: pure functions over immutable entries (passes, breaks, naive baseline)
  ingest.py    CSV to normalised rows with pandas, or every problem by row
  services/    uploads and runs: one function per use case, one transaction each
  routers/     HTTP endpoints
  models.py    SQLAlchemy tables; migrations/ holds the Alembic versions
  demo.py      synthetic statements with planted answers
  cli.py       operator commands: seed, write-samples
dashboard/     React + TypeScript single page, served by nginx
samples/       the synthetic demo statement and ledger
scripts/       container start-up, the smoke test and the benchmark
tests/         pytest: unit, property-based, API, schema and migration tests
```

Design choices and their trade-offs, including the ones that changed after measurement or
review, are recorded in [DECISIONS.md](DECISIONS.md) (D1–D35).

## Done when

- [x] `docker compose up` starts the API, the database and the dashboard (checked by CI on every
      push)
- [x] CI is green on every push
- [x] This README reports measured numbers: rows matched per second against the O(n²)
      baseline, match rate on the seeded data, tests and coverage
