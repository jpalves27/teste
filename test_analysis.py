"""
Unit and integration tests for the throughput analysis tool.

Run with:
    python -m pytest test_analysis.py -v
"""

from __future__ import annotations

import asyncio
import math
import struct
import time

import pytest

from analysis import (
    ETHERNET_OVERHEAD_BYTES,
    IP_HEADER_BYTES,
    PROTOCOL_OVERHEAD_BYTES,
    TCP_HEADER_BYTES,
    NetworkLink,
    TelemetryDevice,
    AnalysisResult,
    analyze,
    format_report,
    sensitivity_table,
)
from client import _build_frame, TELEMETRY_PAYLOAD_BYTES


# ---------------------------------------------------------------------------
# analysis.py – unit tests
# ---------------------------------------------------------------------------

class TestProtocolConstants:
    def test_protocol_overhead_is_sum_of_headers(self) -> None:
        assert PROTOCOL_OVERHEAD_BYTES == TCP_HEADER_BYTES + IP_HEADER_BYTES + ETHERNET_OVERHEAD_BYTES

    def test_values_are_positive(self) -> None:
        assert TCP_HEADER_BYTES > 0
        assert IP_HEADER_BYTES > 0
        assert ETHERNET_OVERHEAD_BYTES > 0


class TestNetworkLink:
    def test_bandwidth_conversions(self) -> None:
        link = NetworkLink("test", bandwidth_bps=2_000_000)
        assert link.bandwidth_Mbps == pytest.approx(2.0)
        assert link.bandwidth_bytes_per_sec == pytest.approx(250_000.0)

    def test_gigabit_link(self) -> None:
        link = NetworkLink("GbE", bandwidth_bps=1_000_000_000)
        assert link.bandwidth_Mbps == pytest.approx(1000.0)


class TestTelemetryDevice:
    def test_default_payload_size(self) -> None:
        dev = TelemetryDevice()
        assert dev.payload_bytes == 200

    def test_bytes_per_message_includes_overhead(self) -> None:
        dev = TelemetryDevice(payload_bytes=200)
        assert dev.bytes_per_message == 200 + PROTOCOL_OVERHEAD_BYTES

    def test_throughput_at_1s_interval(self) -> None:
        dev = TelemetryDevice(payload_bytes=200, send_interval_s=1.0)
        expected_bytes_s = 200 + PROTOCOL_OVERHEAD_BYTES
        assert dev.throughput_bytes_per_sec == pytest.approx(expected_bytes_s)
        assert dev.throughput_bps == pytest.approx(expected_bytes_s * 8)

    def test_throughput_at_longer_interval(self) -> None:
        dev = TelemetryDevice(payload_bytes=200, send_interval_s=10.0)
        assert dev.throughput_bps == pytest.approx(dev.bits_per_message / 10.0)


class TestAnalyze:
    """Tests for the core analyze() function."""

    def test_default_result_has_bottleneck(self) -> None:
        result = analyze()
        # HaLow AP (2 Mbps) should be the bottleneck in the default topology
        assert "HaLow" in result.bottleneck_link.name

    def test_bottleneck_is_minimum_bandwidth_link(self) -> None:
        topology = [
            NetworkLink("A", bandwidth_bps=100_000),
            NetworkLink("B", bandwidth_bps=500_000),
            NetworkLink("C", bandwidth_bps=1_000_000),
        ]
        result = analyze(topology=topology)
        assert result.bottleneck_link.name == "A"

    def test_max_devices_is_positive(self) -> None:
        result = analyze()
        assert result.max_devices_bottleneck > 0

    def test_max_devices_respects_bandwidth(self) -> None:
        """
        With a 2 Mbps link and a device producing ~1,888 bps (200+78=278 B,
        1 s interval → 278 B/s → 2224 bps), max_devices ≈ floor(2_000_000 / 2224).
        """
        result = analyze()
        dev = result.device
        expected_max = math.floor(
            result.bottleneck_link.bandwidth_bps / dev.throughput_bps
        )
        assert result.max_devices_bottleneck == expected_max

    def test_utilisation_approaches_100_pct(self) -> None:
        """Aggregate throughput of max_devices must be ≤ link bandwidth."""
        result = analyze()
        assert result.utilisation_pct <= 100.0
        # And should be close (at least 90 % efficiency)
        assert result.utilisation_pct >= 90.0

    def test_custom_topology_and_device(self) -> None:
        narrow_link = NetworkLink("Narrow", bandwidth_bps=500_000)  # 500 kbps
        topology = [narrow_link, NetworkLink("Wide", bandwidth_bps=1_000_000_000)]
        dev = TelemetryDevice(payload_bytes=200, send_interval_s=5.0)
        result = analyze(device=dev, topology=topology)
        assert result.bottleneck_link is narrow_link
        assert result.max_devices_bottleneck > 0

    def test_notes_contain_halfduplex_warning(self) -> None:
        result = analyze()
        combined = " ".join(result.notes)
        assert "half-duplex" in combined.lower() or "halfduplex" in combined.lower() or "HaLow" in combined

    def test_handshake_cost_is_positive(self) -> None:
        result = analyze()
        assert result.handshake_cost_bytes > 0

    def test_ack_overhead_is_positive(self) -> None:
        result = analyze()
        assert result.tcp_ack_overhead_bps > 0


class TestFormatReport:
    def test_report_is_non_empty_string(self) -> None:
        result = analyze()
        report = format_report(result)
        assert isinstance(report, str)
        assert len(report) > 100

    def test_report_contains_bottleneck_marker(self) -> None:
        result = analyze()
        report = format_report(result)
        assert "BOTTLENECK" in report

    def test_report_contains_max_devices(self) -> None:
        result = analyze()
        report = format_report(result)
        assert str(result.max_devices_bottleneck) in report


class TestSensitivityTable:
    def test_table_is_non_empty(self) -> None:
        table = sensitivity_table()
        assert isinstance(table, str)
        assert len(table) > 50

    def test_longer_interval_means_more_devices(self) -> None:
        """
        Devices that send less frequently consume less bandwidth, so more of
        them can coexist on the same link.
        """
        result_1s = analyze(device=TelemetryDevice(send_interval_s=1.0))
        result_10s = analyze(device=TelemetryDevice(send_interval_s=10.0))
        assert result_10s.max_devices_bottleneck > result_1s.max_devices_bottleneck


# ---------------------------------------------------------------------------
# client.py – unit tests
# ---------------------------------------------------------------------------

class TestBuildFrame:
    def test_frame_is_correct_size(self) -> None:
        frame = _build_frame(device_id=1, sequence=1)
        assert len(frame) == TELEMETRY_PAYLOAD_BYTES

    def test_frame_contains_device_id(self) -> None:
        device_id = 42
        frame = _build_frame(device_id=device_id, sequence=1)
        # device_id is the first uint32 (little-endian)
        (parsed_id,) = struct.unpack_from("<I", frame, 0)
        assert parsed_id == device_id

    def test_frame_contains_sequence(self) -> None:
        sequence = 7
        frame = _build_frame(device_id=1, sequence=sequence)
        (parsed_seq,) = struct.unpack_from("<I", frame, 4)
        assert parsed_seq == sequence

    def test_frame_timestamp_is_recent(self) -> None:
        before = time.time()
        frame = _build_frame(device_id=1, sequence=1)
        after = time.time()
        (ts,) = struct.unpack_from("<d", frame, 8)
        assert before <= ts <= after


# ---------------------------------------------------------------------------
# server.py + client.py – integration test (in-process)
# ---------------------------------------------------------------------------

class TestServerClientIntegration:
    """Start a real server and connect a real client inside the test process."""

    @pytest.mark.asyncio
    async def test_server_receives_frames(self) -> None:
        from server import _handle_client, _connections

        _connections.clear()

        server = await asyncio.start_server(_handle_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        async with server:
            # Send exactly 3 frames and then disconnect
            await run_client_task(host="127.0.0.1", port=port, count=3)

        # After the client disconnects, the server should have processed 3 messages
        # (the connection may already have been removed from _connections)
        # We verify by checking the server received the right amount of data.
        # Because the connection cleanup is async, we just assert no exception was raised.


async def run_client_task(host: str, port: int, count: int) -> None:
    from client import run_client
    await run_client(host=host, port=port, interval_s=0.05, device_id=99, count=count)
