"""Start several uvicorn workers that share port 8000 through SO_REUSEPORT.

With ``uvicorn --workers N`` all workers accept from one shared socket, and a
burst of new connections is often taken by whichever worker wakes first, so
one process ends up serving most of the burst. Here every worker binds its own
socket with SO_REUSEPORT and the Linux kernel spreads new connections evenly
across them.

The number of workers is taken from WEB_CONCURRENCY (default 4). If any worker
exits, the launcher stops the others and exits with an error, so that Docker's
restart policy restarts the container.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import socket
import sys
import time

import uvicorn

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))


def _bind() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind((HOST, PORT))
    sock.listen(2048)
    sock.set_inheritable(True)
    return sock


def _worker() -> None:
    sock = _bind()
    config = uvicorn.Config("app.main:app", log_level="info")
    uvicorn.Server(config).run(sockets=[sock])


def main() -> int:
    workers = max(1, int(os.environ.get("WEB_CONCURRENCY", "4")))
    if workers == 1 or not hasattr(socket, "SO_REUSEPORT"):
        uvicorn.run("app.main:app", host=HOST, port=PORT)
        return 0

    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_worker, name=f"worker-{i}") for i in range(workers)]
    for p in procs:
        p.start()
    print(f"run_server: started {workers} workers on {HOST}:{PORT} (SO_REUSEPORT)", flush=True)

    stopping = False

    def _stop(signum, _frame):
        nonlocal stopping
        stopping = True
        for p in procs:
            if p.is_alive():
                os.kill(p.pid, signal.SIGTERM)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while True:
        if any(not p.is_alive() for p in procs):
            if not stopping:
                print("run_server: a worker exited, stopping", flush=True)
                _stop(signal.SIGTERM, None)
            for p in procs:
                p.join(timeout=10)
            return 0 if stopping else 1
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
