# ReconX

A payment reconciliation engine. It matches a bank statement against an
internal ledger, flags every break (missing, duplicate or mismatched
payments) and shows the match rate on a dashboard.

Built with FastAPI, PostgreSQL and pandas, with a React + TypeScript
dashboard, test-first.

## Status

In progress. This README is the build plan; items are ticked as they land.

## MVP scope

- [ ] CSV ingest for the bank statement and the ledger into PostgreSQL,
      normalising amounts (`Decimal`), dates and references
- [ ] Pass 1: exact reference match with a hash map, O(n)
- [ ] Pass 2: amount and date-window match with sorted two pointers,
      O(n log n)
- [ ] Pass 3: fuzzy reference match (edit distance) on the leftovers only
- [ ] Break types with a reason for each: missing in bank, missing in ledger,
      amount mismatch, duplicate
- [ ] REST API: upload both files, run a reconciliation, list and resolve
      breaks
- [ ] React + TypeScript dashboard: match rate, breaks by type, exception
      queue with manual resolve
- [ ] Benchmark against a naive O(n²) matcher on 100k rows, with the numbers
      in this README
- [ ] pytest suite with coverage (target 80%+), Docker Compose (API, Postgres,
      dashboard), GitHub Actions CI on every push
- [ ] `DECISIONS.md`: each design choice, the alternative considered, and what
      would change with hindsight

## Stack

Python 3.11+ · FastAPI · PostgreSQL 16 · SQLAlchemy 2 · pandas · React ·
TypeScript · pytest · Docker Compose · GitHub Actions

## Done when

- `docker compose up` starts the API, the database and the dashboard
- CI is green on every push
- This README reports measured numbers: rows matched per second against the
  O(n²) baseline, match rate on the seeded data, tests and coverage
