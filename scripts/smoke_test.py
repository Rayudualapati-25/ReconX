"""Check a running stack end to end.

    python scripts/smoke_test.py [http://localhost:8000]

Uses only the standard library, so it runs on any machine with Python 3.
"""

import json
import sys
import urllib.request
from typing import Any

API = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"


def get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
        return json.load(response)


def check(condition: bool, message: str) -> None:
    if not condition:
        sys.exit(f"smoke test failed: {message}")


def main() -> None:
    check(get(f"{API}/health") == {"status": "ok", "database": "ok"}, "API is not healthy")
    print("OK: API and database are healthy")


if __name__ == "__main__":
    main()
