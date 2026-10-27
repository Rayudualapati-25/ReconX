# ReconX

[![CI](https://github.com/Rayudualapati-25/ReconX/actions/workflows/ci.yml/badge.svg)](https://github.com/Rayudualapati-25/ReconX/actions/workflows/ci.yml)

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
- [x] Pass 1: exact reference match with a hash map, O(n)
- [x] Pass 2: amount and date-window match with sorted two pointers,
      O(n log n)
- [x] Pass 3: fuzzy reference match (edit distance) on the leftovers only
      (it runs before pass 2: a similar reference is stronger evidence than a
      shared amount, see DECISIONS D10)
- [x] Break types with a reason for each: missing in bank, missing in ledger,
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

## Development

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and PostgreSQL 16 for the tests.

```bash
uv sync                                   # virtualenv with runtime and dev dependencies
docker run -d --name reconx-test-db -p 5432:5432 \
  -e POSTGRES_USER=reconx -e POSTGRES_PASSWORD=reconx \
  -e POSTGRES_DB=reconx_test postgres:16-alpine
uv run pytest --cov                       # tests with branch coverage (80% floor)
uv run ruff check . && uv run ruff format --check . && uv run mypy
docker compose up --build                 # the API on http://localhost:8000
```

The tests use `TEST_DATABASE_URL` (see `.env.example`) and default to the container above.
Design choices and their trade-offs are recorded in [DECISIONS.md](DECISIONS.md).

## Done when

- `docker compose up` starts the API, the database and the dashboard
- CI is green on every push
- This README reports measured numbers: rows matched per second against the
  O(n²) baseline, match rate on the seeded data, tests and coverage
