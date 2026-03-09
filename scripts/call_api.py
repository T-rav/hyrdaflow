"""Minimal HTTP client for invoking HydraFlow server admin APIs."""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def _build_url(host: str, port: int, path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return f"http://{host}:{port}{path}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Call a HydraFlow HTTP endpoint")
    parser.add_argument("method", help="HTTP method, e.g. POST or GET")
    parser.add_argument("path", help="Endpoint path, e.g. /api/admin/clean")
    parser.add_argument(
        "--port", type=int, default=5555, help="Server port (default: 5555)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)"
    )
    parser.add_argument("--data", help="Raw JSON body to send")

    args = parser.parse_args()
    url = _build_url(args.host, args.port, args.path)
    data_bytes: bytes | None = None
    headers: dict[str, str] = {}
    if args.data:
        try:
            json.loads(args.data)
        except json.JSONDecodeError as exc:  # pragma: no cover - user input
            print(f"Invalid JSON payload: {exc}", file=sys.stderr)
            sys.exit(2)
        data_bytes = args.data.encode()
        headers["Content-Type"] = "application/json"

    try:
        response = httpx.request(
            args.method.upper(),
            url,
            content=data_bytes,
            headers=headers,
            timeout=60.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        text = exc.response.text or str(exc)
        print(text, file=sys.stderr)
        status = exc.response.status_code
        sys.exit(status if status >= 400 else 1)
    except httpx.RequestError as exc:
        print(f"Failed to call {url}: {exc}", file=sys.stderr)
        sys.exit(1)
    else:
        if response.text:
            print(response.text)


if __name__ == "__main__":
    main()
