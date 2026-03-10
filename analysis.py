"""
Throughput and bottleneck analysis for the IoT telemetry network.

Topology: Server <- Network Switch <- HaLow AP <- Edge Devices

Each edge device establishes a TCP connection to a central server and
continuously pushes 200-byte telemetry payloads.  The HaLow access point
is the narrow link in the chain (2 Mbps by default).

Run directly for an interactive report:
    python analysis.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Physical / protocol constants
# ---------------------------------------------------------------------------

# Minimum TCP header size (bytes)
TCP_HEADER_BYTES: int = 20

# Minimum IPv4 header size (bytes)
IP_HEADER_BYTES: int = 20

# Ethernet II frame overhead:
#   Preamble 7 + SFD 1 + Dst MAC 6 + Src MAC 6 + EtherType 2 + FCS 4 = 26
#   Plus minimum inter-frame gap equivalent to 12 bytes on the wire.
ETHERNET_OVERHEAD_BYTES: int = 38

# Total L2/L3/L4 overhead per data segment (bytes)
PROTOCOL_OVERHEAD_BYTES: int = TCP_HEADER_BYTES + IP_HEADER_BYTES + ETHERNET_OVERHEAD_BYTES

# TCP three-way handshake: 3 control segments (SYN, SYN-ACK, ACK) each ~60 B
TCP_HANDSHAKE_SEGMENTS: int = 3
TCP_CONTROL_SEGMENT_BYTES: int = 60  # TCP options + headers, no data

# TCP ACK generated for every other segment (delayed ACK) – 1 ACK ≈ 60 B
TCP_ACK_BYTES: int = 60


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NetworkLink:
    """Represents a single point-to-point link in the topology."""
    name: str
    bandwidth_bps: float  # bits per second

    @property
    def bandwidth_Mbps(self) -> float:
        return self.bandwidth_bps / 1_000_000

    @property
    def bandwidth_bytes_per_sec(self) -> float:
        return self.bandwidth_bps / 8


@dataclass
class TelemetryDevice:
    """Simulated edge device that sends periodic telemetry."""
    payload_bytes: int = 200        # application data per message
    send_interval_s: float = 1.0   # seconds between successive pushes

    @property
    def bytes_per_message(self) -> int:
        """Total on-wire bytes per telemetry message (payload + overhead)."""
        return self.payload_bytes + PROTOCOL_OVERHEAD_BYTES

    @property
    def bits_per_message(self) -> int:
        return self.bytes_per_message * 8

    @property
    def throughput_bytes_per_sec(self) -> float:
        """Steady-state throughput produced by one device."""
        return self.bytes_per_message / self.send_interval_s

    @property
    def throughput_bps(self) -> float:
        return self.throughput_bytes_per_sec * 8


@dataclass
class AnalysisResult:
    """Results produced by :func:`analyze`."""
    topology: List[NetworkLink]
    device: TelemetryDevice
    bottleneck_link: NetworkLink
    max_devices_bottleneck: int
    device_throughput_bps: float
    aggregate_throughput_bps: float  # all max_devices transmitting simultaneously
    utilisation_pct: float
    handshake_cost_bytes: int        # one-time TCP setup cost per device
    tcp_ack_overhead_bps: float      # ACK traffic heading *upstream* (server→AP)
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------

def analyze(
    device: TelemetryDevice | None = None,
    topology: List[NetworkLink] | None = None,
) -> AnalysisResult:
    """
    Compute throughput metrics and identify the bottleneck link.

    Parameters
    ----------
    device:
        Edge-device configuration.  Defaults to a device sending 200-byte
        payloads every second.
    topology:
        Ordered list of :class:`NetworkLink` objects from *edge* to *server*.
        Defaults to the reference topology described in the problem statement
        (HaLow AP at 2 Mbps, Gigabit switch, Gigabit server NIC).

    Returns
    -------
    AnalysisResult
    """
    if device is None:
        device = TelemetryDevice()

    if topology is None:
        topology = [
            NetworkLink("HaLow AP (edge→server)",   bandwidth_bps=2_000_000),  # 2 Mbps
            NetworkLink("Network Switch (AP→server)", bandwidth_bps=1_000_000_000),  # 1 Gbps
            NetworkLink("Server NIC",                bandwidth_bps=1_000_000_000),  # 1 Gbps
        ]

    # --- Bottleneck: link with the lowest bandwidth ---
    bottleneck = min(topology, key=lambda lnk: lnk.bandwidth_bps)

    # --- Per-device throughput ---
    dev_bps = device.throughput_bps

    # --- Maximum devices the bottleneck can sustain ---
    max_devs = math.floor(bottleneck.bandwidth_bps / dev_bps)

    # --- Aggregate throughput at saturation ---
    aggregate_bps = max_devs * dev_bps

    # --- Utilisation ---
    utilisation = (aggregate_bps / bottleneck.bandwidth_bps) * 100

    # --- TCP handshake one-time cost per device ---
    handshake_cost = TCP_HANDSHAKE_SEGMENTS * TCP_CONTROL_SEGMENT_BYTES

    # --- ACK traffic (server → devices) through the bottleneck ---
    # Delayed ACK: one ACK per two data segments.  For a device sending 1
    # message/s the server replies with roughly 0.5 ACK/s.
    acks_per_sec_per_device = 1 / (2 * device.send_interval_s)
    ack_bps_per_device = acks_per_sec_per_device * TCP_ACK_BYTES * 8
    total_ack_bps = ack_bps_per_device * max_devs

    # --- Annotations ---
    notes: List[str] = []

    if utilisation > 80:
        notes.append(
            f"WARNING: bottleneck link '{bottleneck.name}' will exceed 80 % "
            f"utilisation with {max_devs} devices – congestion likely."
        )

    if device.send_interval_s < 0.5:
        notes.append(
            "CAUTION: send interval < 0.5 s may overwhelm the TCP stack on "
            "resource-constrained edge devices."
        )

    if bottleneck.bandwidth_bps < 1_000_000:
        notes.append(
            "CAUTION: bottleneck bandwidth < 1 Mbps – consider payload "
            "compression or longer send intervals."
        )

    notes.append(
        "NOTE: HaLow (802.11ah) half-duplex contention and retransmissions "
        "reduce effective throughput by 20-40 % in dense deployments."
    )
    notes.append(
        "NOTE: TCP keeps connections alive; each persistent connection "
        "consumes a file descriptor and ~4 KB of kernel buffer on the server."
    )

    return AnalysisResult(
        topology=topology,
        device=device,
        bottleneck_link=bottleneck,
        max_devices_bottleneck=max_devs,
        device_throughput_bps=dev_bps,
        aggregate_throughput_bps=aggregate_bps,
        utilisation_pct=utilisation,
        handshake_cost_bytes=handshake_cost,
        tcp_ack_overhead_bps=total_ack_bps,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def format_report(result: AnalysisResult) -> str:
    """Return a human-readable analysis report."""
    lines: List[str] = []
    sep = "=" * 65

    lines.append(sep)
    lines.append("  IoT Telemetry Network – Throughput & Bottleneck Analysis")
    lines.append(sep)

    # Topology
    lines.append("\n[ Network Topology (edge → server) ]")
    for i, link in enumerate(result.topology, start=1):
        marker = " *** BOTTLENECK ***" if link is result.bottleneck_link else ""
        lines.append(
            f"  {i}. {link.name:40s}  {link.bandwidth_Mbps:8.2f} Mbps{marker}"
        )

    # Device parameters
    dev = result.device
    lines.append("\n[ Edge-Device Parameters ]")
    lines.append(f"  Telemetry payload size : {dev.payload_bytes} bytes")
    lines.append(f"  Protocol overhead      : {PROTOCOL_OVERHEAD_BYTES} bytes")
    lines.append(f"  Total on-wire per msg  : {dev.bytes_per_message} bytes")
    lines.append(f"  Send interval          : {dev.send_interval_s} s")
    lines.append(f"  Throughput (1 device)  : {dev.throughput_bps:,.1f} bps  "
                 f"({dev.throughput_bytes_per_sec:,.1f} B/s)")

    # Bottleneck summary
    bn = result.bottleneck_link
    lines.append("\n[ Bottleneck Analysis ]")
    lines.append(f"  Bottleneck link        : {bn.name}")
    lines.append(f"  Bottleneck bandwidth   : {bn.bandwidth_Mbps:.2f} Mbps")
    lines.append(f"  Max sustainable devices: {result.max_devices_bottleneck}")
    lines.append(
        f"  Aggregate throughput   : {result.aggregate_throughput_bps / 1_000:.1f} kbps  "
        f"({result.aggregate_throughput_bps / 8_000:.1f} KB/s)"
    )
    lines.append(f"  Link utilisation       : {result.utilisation_pct:.1f} %")

    # TCP overhead details
    lines.append("\n[ TCP Overhead ]")
    lines.append(
        f"  Handshake cost/device  : {result.handshake_cost_bytes} bytes (one-time)"
    )
    lines.append(
        f"  ACK return traffic     : {result.tcp_ack_overhead_bps:,.1f} bps "
        f"(server → devices, all {result.max_devices_bottleneck} devices)"
    )

    # Notes / warnings
    if result.notes:
        lines.append("\n[ Notes & Warnings ]")
        for note in result.notes:
            lines.append(f"  • {note}")

    lines.append("\n" + sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sensitivity analysis
# ---------------------------------------------------------------------------

def sensitivity_table(
    device: TelemetryDevice | None = None,
    topology: List[NetworkLink] | None = None,
    intervals: List[float] | None = None,
) -> str:
    """
    Return a table showing how *send_interval_s* affects the maximum number
    of supported devices.
    """
    if intervals is None:
        intervals = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]

    base_device = device or TelemetryDevice()
    lines = [
        "\n[ Sensitivity: send interval vs. max devices on bottleneck ]",
        f"  {'Interval (s)':>14}  {'Max devices':>12}  {'Link util %':>12}",
        "  " + "-" * 42,
    ]

    for interval in intervals:
        dev = TelemetryDevice(
            payload_bytes=base_device.payload_bytes,
            send_interval_s=interval,
        )
        res = analyze(device=dev, topology=topology)
        lines.append(
            f"  {interval:>14.1f}  {res.max_devices_bottleneck:>12d}  "
            f"{res.utilisation_pct:>11.1f}%"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = analyze()
    print(format_report(result))
    print(sensitivity_table())
