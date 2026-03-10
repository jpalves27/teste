"""
Edge-device TCP client that periodically pushes 200-byte telemetry frames
to the central server.

Usage:
    python client.py [--host HOST] [--port PORT] [--interval SECONDS]
                     [--device-id ID] [--count N]

The client connects to the server, then sends one fixed-size telemetry
frame every *interval* seconds.  If ``--count`` is specified the client
exits after sending that many frames; otherwise it runs until interrupted.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import struct
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

TELEMETRY_PAYLOAD_BYTES: int = 200
DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 9000
DEFAULT_INTERVAL_S: float = 1.0
ACK_BYTE: bytes = b"\x06"  # ASCII ACK expected from the server


# ---------------------------------------------------------------------------
# Telemetry frame builder
# ---------------------------------------------------------------------------

def _build_frame(device_id: int, sequence: int) -> bytes:
    """
    Build a fixed-size 200-byte telemetry frame.

    Layout (little-endian):
      Bytes  0- 3  : device_id  (uint32)
      Bytes  4- 7  : sequence   (uint32)
      Bytes  8-15  : timestamp  (float64, UNIX epoch seconds)
      Bytes 16-19  : payload CRC placeholder (uint32, zero)
      Bytes 20-199 : zero-padded application data (180 bytes)
    """
    header = struct.pack(
        "<IId I",
        device_id & 0xFFFFFFFF,
        sequence & 0xFFFFFFFF,
        time.time(),
        0,           # CRC placeholder
    )  # 20 bytes

    # Fill the remaining 180 bytes with a repeating pattern (simulated sensor data)
    padding = bytes(range(256)) * 2  # 512 bytes; we slice what we need
    body = padding[: TELEMETRY_PAYLOAD_BYTES - len(header)]

    frame = header + body
    assert len(frame) == TELEMETRY_PAYLOAD_BYTES, (
        f"Frame size mismatch: expected {TELEMETRY_PAYLOAD_BYTES}, got {len(frame)}"
    )
    return frame


# ---------------------------------------------------------------------------
# Client coroutine
# ---------------------------------------------------------------------------

async def run_client(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    interval_s: float = DEFAULT_INTERVAL_S,
    device_id: int = 1,
    count: int | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Connect to the telemetry server and push frames at *interval_s* rate."""
    if logger is None:
        logger = logging.getLogger(__name__)

    prefix = f"[device-{device_id}]"
    logger.info("%s Connecting to %s:%d …", prefix, host, port)

    reader, writer = await asyncio.open_connection(host, port)
    logger.info("%s Connected.", prefix)

    sent = 0
    start = time.monotonic()

    try:
        while count is None or sent < count:
            frame = _build_frame(device_id, sent + 1)
            writer.write(frame)
            await writer.drain()
            sent += 1

            elapsed = time.monotonic() - start
            throughput_bps = (sent * TELEMETRY_PAYLOAD_BYTES * 8) / max(elapsed, 1e-9)

            logger.info(
                "%s Sent frame #%d  cumulative_bps=%.1f  elapsed=%.1f s",
                prefix,
                sent,
                throughput_bps,
                elapsed,
            )

            # Wait for ACK if the server sends one
            try:
                ack = await asyncio.wait_for(reader.readexactly(1), timeout=interval_s)
                if ack != ACK_BYTE:
                    logger.warning("%s Unexpected ACK byte: %r", prefix, ack)
            except asyncio.TimeoutError:
                logger.debug("%s No ACK received within %.1f s (server may have ACK disabled)", prefix, interval_s)

            await asyncio.sleep(interval_s)

    except asyncio.CancelledError:
        logger.info("%s Client cancelled after %d frames.", prefix, sent)
    except Exception as exc:  # noqa: BLE001
        logger.error("%s Client error: %s", prefix, exc)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass

    elapsed = time.monotonic() - start
    logger.info(
        "%s Done. Sent %d frames in %.1f s  avg_bps=%.1f",
        prefix,
        sent,
        elapsed,
        (sent * TELEMETRY_PAYLOAD_BYTES * 8) / max(elapsed, 1e-9),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="IoT Edge Device – Telemetry Client")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server TCP port")
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL_S,
        help="Seconds between successive telemetry pushes",
    )
    parser.add_argument(
        "--device-id", type=int, default=int(os.getenv("DEVICE_ID", "1")),
        help="Logical device identifier embedded in each frame",
    )
    parser.add_argument(
        "--count", type=int, default=None,
        help="Exit after sending this many frames (default: run forever)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(
        run_client(
            host=args.host,
            port=args.port,
            interval_s=args.interval,
            device_id=args.device_id,
            count=args.count,
        )
    )
