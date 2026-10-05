"""ASGI entry point for the assembled Covenia backend.

``create_app`` is the one composition root: it delegates to
:mod:`covenia_b.runtime` and never adds a rule, a route, or an error mapping of
its own.  ``python -m covenia_b.main`` serves the same application on a
loopback-only listener, because the competition build has no authentication
boundary and must not be reachable from another host.
"""

from __future__ import annotations

import argparse
import ipaddress
import sys
from collections.abc import Sequence

from fastapi import FastAPI

from covenia_b.runtime import Runtime, compose_application
from covenia_b.settings import Settings, get_settings

LOOPBACK_ERROR = "the service may only listen on a loopback address"


def create_app(settings: Settings | None = None, *, runtime: Runtime | None = None) -> FastAPI:
    """Build the single composed application; no external resource is opened."""

    return compose_application(settings or get_settings(), runtime=runtime)


app = create_app()


def _loopback(host: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        if host == "localhost":
            return host
        raise ValueError(LOOPBACK_ERROR) from error
    if not address.is_loopback:
        raise ValueError(LOOPBACK_ERROR)
    return host


def main(argv: Sequence[str] | None = None) -> int:
    """Serve the composed application on loopback only."""

    parser = argparse.ArgumentParser(description="Run the Covenia backend locally")
    parser.add_argument("--host", default=None, help="loopback host (default from settings)")
    parser.add_argument("--port", type=int, default=None, help="port (default from settings)")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    settings = get_settings()
    host = args.host if args.host is not None else settings.listen_host
    port = args.port if args.port is not None else settings.listen_port
    try:
        host = _loopback(host)
    except ValueError as error:
        print(f"refusing to start: {error}", file=sys.stderr)
        return 2
    if not 1 <= port <= 65535:
        print("refusing to start: port must be between 1 and 65535", file=sys.stderr)
        return 2

    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
