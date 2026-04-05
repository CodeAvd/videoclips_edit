import argparse
import asyncio
import socket
from uuid import uuid4

from app.services.worker_runtime import run_worker_loop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Shorts Engine worker runtime")
    parser.add_argument("--once", action="store_true", help="Process at most one available outbox event.")
    parser.add_argument("--max-events", type=int, default=None, help="Stop after processing N events.")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds.")
    parser.add_argument("--worker-id", type=str, default=f"{socket.gethostname()}-{uuid4()}", help="Logical worker identifier.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await run_worker_loop(
        worker_id=args.worker_id,
        poll_interval_seconds=args.poll_interval,
        once=args.once,
        max_events=args.max_events,
    )


if __name__ == "__main__":
    asyncio.run(main())
