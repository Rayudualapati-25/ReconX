"""Check a running stack end to end: the API, the seeded demo run, and the dashboard.

    python scripts/smoke_test.py [http://localhost:8000] [http://localhost:3000]

Uses only the standard library, so it runs on any machine with Python 3.
"""

import json
import sys
import urllib.request
from typing import Any

API = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
DASHBOARD = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:3000"


def get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
        return json.load(response)


def page(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
        body: str = response.read().decode()
        return body


def check(condition: bool, message: str) -> None:
    if not condition:
        sys.exit(f"smoke test failed: {message}")


def main() -> None:
    check(get(f"{API}/health") == {"status": "ok", "database": "ok"}, "API is not healthy")
    runs = get(f"{API}/runs")
    check(len(runs) >= 1, "the demo run was not seeded")
    run = get(f"{API}/runs/{runs[-1]['id']}")
    check(run["match_rate"] > 0.9, f"the demo match rate is only {run['match_rate']}")
    queue = get(f"{API}/runs/{run['id']}/breaks?status=open&limit=5")
    check(queue["total"] == run["open_breaks"] > 0, "the exception queue does not match the run")
    check('<div id="root">' in page(DASHBOARD), "the dashboard does not serve its page")
    proxied = get(f"{DASHBOARD}/api/runs/{run['id']}")
    check(proxied["id"] == run["id"], "the dashboard does not forward /api to the API")
    print(
        f"OK: API healthy; demo run {run['id']} matched {run['match_rate']:.2%} of "
        f"{run['bank_count'] + run['ledger_count']:,} entries, {run['open_breaks']} breaks open; "
        "dashboard served and /api forwarded"
    )


if __name__ == "__main__":
    main()
