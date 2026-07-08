"""
SB-689 Free-Flow Pipeline
=========================

SB-689 is the fast, unrestricted data-processing layer that sits between the
SB-712 watchdog and the SB-688 data-integrity kernel.

Architecture position:

    Windows OS
        ↕
    SB-712 CorruptionGuard  ← strict watchdog (triple verification, convoy)
        ↕
    SB-689 FreeFlowPipeline ← THIS MODULE — fast, trusted-path processing
        ↕
    SB-688 data integrity   ← bottom integrity kernel (BlockStore, WAL, ECC)

Design principle:
    SB-689 carries data that has *already* been cleared by the SB-712 trust
    gate.  It does not re-run triple verification; instead it enforces a
    single lightweight integrity seal (SHA-256) so that tampering in transit
    is still detectable, while keeping throughput high.

    "689 flows free" — no convoy, no quarantine, no three-pass gate.
    One seal.  One check.  Fast path.

Components:
    FlowPacket      — a sealed unit of data moving through the pipeline.
    FlowChannel     — a named directional channel between two nodes.
    FreeFlowPipeline — orchestrates channels, routes packets, and records
                       throughput metrics.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
import uuid


# ---------------------------------------------------------------------------
# FlowPacket
# ---------------------------------------------------------------------------

@dataclass
class FlowPacket:
    """
    A lightweight, sealed unit of data.

    ``payload`` is arbitrary bytes — whatever the pipeline carries.
    ``seal``    is SHA-256(origin + destination + payload) computed on creation.
    """

    packet_id: str
    origin: str
    destination: str
    payload: bytes
    seal: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    metadata: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.seal:
            self.seal = self._compute_seal()

    def _compute_seal(self) -> str:
        raw = self.origin.encode() + self.destination.encode() + self.payload
        return hashlib.sha256(raw).hexdigest()

    def verify_seal(self) -> bool:
        """Return True if the packet has not been tampered with since creation."""
        return self.seal == self._compute_seal()


def make_packet(origin: str, destination: str, payload: bytes) -> FlowPacket:
    """Convenience constructor — auto-generates a packet_id and seal."""
    return FlowPacket(
        packet_id=str(uuid.uuid4()),
        origin=origin,
        destination=destination,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# FlowChannel
# ---------------------------------------------------------------------------

@dataclass
class ChannelStats:
    sent: int = 0
    received: int = 0
    tamper_detected: int = 0
    dropped: int = 0


class FlowChannel:
    """
    A named, directional conduit between *origin* and *destination*.

    Packets with a broken seal are detected and counted as tampered;
    they are dropped rather than forwarded.
    """

    def __init__(self, name: str, origin: str, destination: str) -> None:
        self.name = name
        self.origin = origin
        self.destination = destination
        self.stats = ChannelStats()
        self._queue: List[FlowPacket] = []

    def send(self, packet: FlowPacket) -> bool:
        """
        Enqueue *packet*.  Returns True if accepted, False if seal check fails.
        """
        self.stats.sent += 1
        if not packet.verify_seal():
            self.stats.tamper_detected += 1
            self.stats.dropped += 1
            return False
        self._queue.append(packet)
        return True

    def receive_all(self) -> List[FlowPacket]:
        """Drain and return all queued packets."""
        packets = list(self._queue)
        self._queue.clear()
        self.stats.received += len(packets)
        return packets

    def pending(self) -> int:
        return len(self._queue)


# ---------------------------------------------------------------------------
# FreeFlowPipeline
# ---------------------------------------------------------------------------

ProcessorFn = Callable[[FlowPacket], Optional[bytes]]


@dataclass
class PipelineRun:
    """Summary of a single pipeline execution."""

    run_id: str
    packets_in: int
    packets_out: int
    tamper_detected: int
    processor_errors: int
    started_at: datetime
    completed_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @property
    def success_rate(self) -> float:
        if self.packets_in == 0:
            return 1.0
        return self.packets_out / self.packets_in


class FreeFlowPipeline:
    """
    SB-689 free-flow pipeline.

    Registers named channels and optional processor functions.
    Processors transform packet payloads; the result is resealed and
    forwarded to the next channel.

    Usage::

        pipeline = FreeFlowPipeline()
        pipeline.add_channel(FlowChannel("ingest", "source", "processor"))
        pipeline.add_channel(FlowChannel("output", "processor", "sink"))
        pipeline.add_processor("processor", my_transform_fn)

        packet = make_packet("source", "processor", b"data")
        result = pipeline.run([packet])
    """

    def __init__(self) -> None:
        self._channels: Dict[str, FlowChannel] = {}
        self._processors: Dict[str, ProcessorFn] = {}
        self._run_history: List[PipelineRun] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add_channel(self, channel: FlowChannel) -> None:
        self._channels[channel.name] = channel

    def add_processor(self, node_name: str, fn: ProcessorFn) -> None:
        """Register a processing function for *node_name*."""
        self._processors[node_name] = fn

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, packets: List[FlowPacket]) -> PipelineRun:
        """
        Route *packets* through all registered channels in order.

        Each packet is passed to a processor for its destination node
        (if one is registered); the transformed payload is resealed and
        forwarded to the next channel whose origin matches the destination.
        """
        started_at = datetime.now(tz=timezone.utc)
        packets_out = 0
        tamper_detected = 0
        processor_errors = 0

        current = list(packets)

        for channel in self._channels.values():
            next_wave: List[FlowPacket] = []
            for pkt in current:
                if pkt.destination != channel.origin and pkt.origin != channel.origin:
                    next_wave.append(pkt)
                    continue
                accepted = channel.send(pkt)
                if not accepted:
                    tamper_detected += 1
                    continue

            # Drain the channel, apply processor, and build forwarded packets.
            for received in channel.receive_all():
                dest_node = received.destination
                processor = self._processors.get(dest_node)
                if processor is not None:
                    try:
                        new_payload = processor(received)
                    except Exception:
                        processor_errors += 1
                        continue
                    if new_payload is None:
                        processor_errors += 1
                        continue
                    forwarded = make_packet(dest_node, channel.destination, new_payload)
                    next_wave.append(forwarded)
                else:
                    next_wave.append(received)
                packets_out += 1

            current = next_wave

        run = PipelineRun(
            run_id=str(uuid.uuid4()),
            packets_in=len(packets),
            packets_out=packets_out,
            tamper_detected=tamper_detected,
            processor_errors=processor_errors,
            started_at=started_at,
            completed_at=datetime.now(tz=timezone.utc),
        )
        self._run_history.append(run)
        return run

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def channel_stats(self, channel_name: str) -> Optional[ChannelStats]:
        ch = self._channels.get(channel_name)
        return ch.stats if ch else None

    def run_history(self) -> List[PipelineRun]:
        return list(self._run_history)

    def total_packets_routed(self) -> int:
        return sum(r.packets_out for r in self._run_history)
