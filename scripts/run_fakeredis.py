#!/usr/bin/env python3
"""Standalone fakeredis TCP server for local dev.

Lets the uvicorn API and arq worker — separate processes — share one
Redis-compatible store without a real Redis install. The test suite doesn't
use this: it wires an in-process `fakeredis.aioredis.FakeRedis` directly
(see tests/queue/test_tasks.py, tests/api/test_jobs.py). This script exists
only for `dev.sh`, where two independent processes need to talk to the same
fake store over a socket.
"""

from __future__ import annotations

import sys

from fakeredis import TcpFakeServer


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 6379

    server = TcpFakeServer((host, port))
    print(f"fakeredis listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
