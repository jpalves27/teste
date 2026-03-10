"""
Multi-device load simulation.

Starts the TCP server in-process and spawns *N* simulated edge-device
clients concurrently.  After all clients finish sending their frames the
server prints aggregate throughput statistics.

Usage:
    python simulation.py [--devices N] [--count FRAMES] [--interval SECONDS]
                         [--host HOST] [--port PORT]

Example – simulate 100 devices each sending 10 frames every 1 second:
    python simulation.py --devices 100 --count 10 --interval 1.0
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from client import run_client, TELEMETRY_PAYLOAD_BYTES
from server import run_server, _connections, _print_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 9100  # separate port to avoid conflicts with a standalone server
DEFAULT_DEVICES: int = 10
DEFAULT_COUNT: int = 5
DEFAULT_INTERVAL_S: float = 1.0


# ---------------------------------------------------------------------------
# Simulation runner
# ---------------------------------------------------------------------------

async def _run_simulation(
    host: str,
    port: int,
    num_devices: int,
    frames_per_device: int,
    interval_s: float,
) -> None:
    logger.info(
        "Starting simulation: %d devices × %d frames @ %.1f s interval",
        num_devices, frames_per_device, interval_s,
    )

    # Start the server as a background task
    server_task = asyncio.create_task(run_server(host=host, port=port))

    # Give the server a moment to bind the socket
    await asyncio.sleep(0.5)

    # Spawn all device clients concurrently
    start_time = time.monotonic()

    device_tasks = [
        asyncio.create_task(
            run_client(
                host=host,
                port=port,
                interval_s=interval_s,
                device_id=i + 1,
                count=frames_per_device,
            )
        )
        for i in range(num_devices)
    ]

    await asyncio.gather(*device_tasks, return_exceptions=True)

    elapsed = time.monotonic() - start_time
    total_frames = num_devices * frames_per_device
    total_bytes = total_frames * TELEMETRY_PAYLOAD_BYTES
    total_bps = (total_bytes * 8) / max(elapsed, 1e-9)

    logger.info("=" * 65)
    logger.info("Simulation complete in %.2f s", elapsed)
    logger.info("  Devices           : %d", num_devices)
    logger.info("  Frames per device : %d", frames_per_device)
    logger.info("  Total frames      : %d", total_frames)
    logger.info("  Total payload     : %d bytes", total_bytes)
    logger.info(
        "  Aggregate bps     : %.1f bps  (%.2f KB/s)",
        total_bps,
        total_bps / 8 / 1024,
    )
    logger.info("=" * 65)

    _print_stats()

    # Shut down the server
    server_task.cancel()
    try:
        await server_task
    except (asyncio.CancelledError, Exception):
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="IoT Telemetry Network – Multi-device load simulation"
    )
    parser.add_argument(
        "--devices", type=int, default=DEFAULT_DEVICES,
        help="Number of simulated edge devices",
    )
    parser.add_argument(
        "--count", type=int, default=DEFAULT_COUNT,
        help="Number of telemetry frames each device sends",
    )
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL_S,
        help="Seconds between successive frames from each device",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server bind/connect address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(
        _run_simulation(
            host=args.host,
            port=args.port,
            num_devices=args.devices,
            frames_per_device=args.count,
            interval_s=args.interval,
        )
    )
