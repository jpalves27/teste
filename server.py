"""
Async TCP server that receives 200-byte telemetry packets from edge devices.

Usage:
    python server.py [--host HOST] [--port PORT]

The server listens for incoming connections, reads fixed-size 200-byte
telemetry frames, logs basic throughput statistics, and optionally sends
an acknowledgement back to the client.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TELEMETRY_PAYLOAD_BYTES: int = 200
DEFAULT_HOST: str = "0.0.0.0"
DEFAULT_PORT: int = 9000
STATS_INTERVAL_S: float = 5.0      # Print throughput stats every N seconds
ACK_ENABLED: bool = True           # Send a 1-byte ACK for each received message


# ---------------------------------------------------------------------------
# Per-connection state
# ---------------------------------------------------------------------------

@dataclass
class ConnectionStats:
    remote: str
    connected_at: float = field(default_factory=time.monotonic)
    messages_received: int = 0
    bytes_received: int = 0

    def throughput_bps(self) -> float:
        elapsed = time.monotonic() - self.connected_at
        if elapsed <= 0:
            return 0.0
        return (self.bytes_received * 8) / elapsed


# ---------------------------------------------------------------------------
# Global stats aggregator
# ---------------------------------------------------------------------------

_connections: Dict[str, ConnectionStats] = {}


def _print_stats() -> None:
    if not _connections:
        logger.info("No active connections.")
        return

    total_msgs = sum(c.messages_received for c in _connections.values())
    total_bytes = sum(c.bytes_received for c in _connections.values())
    total_bps = sum(c.throughput_bps() for c in _connections.values())

    logger.info(
        "=== Server Stats | connections=%d | total_messages=%d | "
        "total_bytes=%d | aggregate_throughput=%.1f bps (%.2f KB/s) ===",
        len(_connections),
        total_msgs,
        total_bytes,
        total_bps,
        total_bps / 8 / 1024,
    )
    for remote, stats in _connections.items():
        logger.info(
            "  [%s] msgs=%d bytes=%d bps=%.1f",
            remote,
            stats.messages_received,
            stats.bytes_received,
            stats.throughput_bps(),
        )


# ---------------------------------------------------------------------------
# Connection handler
# ---------------------------------------------------------------------------

async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    remote_addr: Tuple[str, int] = writer.get_extra_info("peername")
    remote = f"{remote_addr[0]}:{remote_addr[1]}"
    stats = ConnectionStats(remote=remote)
    _connections[remote] = stats

    logger.info("Client connected: %s  (total connections: %d)", remote, len(_connections))

    try:
        while True:
            # Read exactly TELEMETRY_PAYLOAD_BYTES bytes (framed protocol)
            data = await reader.readexactly(TELEMETRY_PAYLOAD_BYTES)

            stats.messages_received += 1
            stats.bytes_received += len(data)

            logger.debug(
                "Received %d bytes from %s (msg #%d)",
                len(data),
                remote,
                stats.messages_received,
            )

            if ACK_ENABLED:
                # Send a minimal 1-byte acknowledgement
                writer.write(b"\x06")  # ASCII ACK
                await writer.drain()

    except asyncio.IncompleteReadError:
        logger.info("Client disconnected (incomplete read): %s", remote)
    except asyncio.CancelledError:
        logger.info("Handler cancelled for %s", remote)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error handling client %s: %s", remote, exc)
    finally:
        _connections.pop(remote, None)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        logger.info("Connection closed: %s  (remaining: %d)", remote, len(_connections))


# ---------------------------------------------------------------------------
# Periodic stats printer
# ---------------------------------------------------------------------------

async def _stats_loop() -> None:
    while True:
        await asyncio.sleep(STATS_INTERVAL_S)
        _print_stats()


# ---------------------------------------------------------------------------
# Server bootstrap
# ---------------------------------------------------------------------------

async def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = await asyncio.start_server(_handle_client, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    logger.info("TCP telemetry server listening on %s", addrs)

    stats_task = asyncio.create_task(_stats_loop())

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    async with server:
        await stop_event.wait()

    stats_task.cancel()
    _print_stats()
    logger.info("Server stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="IoT Telemetry TCP Server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(run_server(host=args.host, port=args.port))
