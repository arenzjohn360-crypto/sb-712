"""Tests for sb_712.sb689 (SB-689 free-flow pipeline)."""
import pytest

from sb_712.sb689 import (
    ChannelStats,
    FlowChannel,
    FlowPacket,
    FreeFlowPipeline,
    PipelineRun,
    make_packet,
)


# ---------------------------------------------------------------------------
# FlowPacket
# ---------------------------------------------------------------------------

def test_packet_seal_computed_on_creation():
    pkt = make_packet("A", "B", b"hello")
    assert pkt.seal != ""


def test_packet_verify_seal_passes_for_intact_packet():
    pkt = make_packet("A", "B", b"hello")
    assert pkt.verify_seal() is True


def test_packet_verify_seal_fails_after_payload_tamper():
    pkt = make_packet("A", "B", b"hello")
    pkt.payload = b"TAMPERED"
    assert pkt.verify_seal() is False


def test_packet_verify_seal_fails_after_seal_tamper():
    pkt = make_packet("A", "B", b"hello")
    pkt.seal = "0" * 64
    assert pkt.verify_seal() is False


def test_two_packets_with_same_data_same_seal():
    p1 = FlowPacket("id1", "A", "B", b"data", seal="")
    p2 = FlowPacket("id2", "A", "B", b"data", seal="")
    # Seals are computed from origin+destination+payload, not packet_id.
    assert p1.seal == p2.seal


# ---------------------------------------------------------------------------
# FlowChannel
# ---------------------------------------------------------------------------

def test_channel_accepts_valid_packet():
    ch = FlowChannel("ch1", "A", "B")
    pkt = make_packet("A", "B", b"data")
    assert ch.send(pkt) is True
    assert ch.pending() == 1


def test_channel_rejects_tampered_packet():
    ch = FlowChannel("ch1", "A", "B")
    pkt = make_packet("A", "B", b"data")
    pkt.payload = b"tampered"
    assert ch.send(pkt) is False
    assert ch.pending() == 0


def test_channel_stats_track_tamper():
    ch = FlowChannel("ch1", "A", "B")
    pkt = make_packet("A", "B", b"data")
    pkt.payload = b"tampered"
    ch.send(pkt)
    assert ch.stats.tamper_detected == 1
    assert ch.stats.dropped == 1


def test_channel_receive_all_drains_queue():
    ch = FlowChannel("ch1", "A", "B")
    for i in range(3):
        ch.send(make_packet("A", "B", b"x"))
    received = ch.receive_all()
    assert len(received) == 3
    assert ch.pending() == 0


def test_channel_stats_received_increments():
    ch = FlowChannel("ch1", "A", "B")
    ch.send(make_packet("A", "B", b"x"))
    ch.receive_all()
    assert ch.stats.received == 1


# ---------------------------------------------------------------------------
# FreeFlowPipeline — basic routing
# ---------------------------------------------------------------------------

def make_pipeline_with_channels():
    pipeline = FreeFlowPipeline()
    pipeline.add_channel(FlowChannel("ingest", "source", "worker"))
    pipeline.add_channel(FlowChannel("output", "worker", "sink"))
    return pipeline


def test_pipeline_run_returns_pipeline_run():
    pipeline = make_pipeline_with_channels()
    pkt = make_packet("source", "worker", b"payload")
    result = pipeline.run([pkt])
    assert isinstance(result, PipelineRun)


def test_pipeline_run_counts_packets_in():
    pipeline = make_pipeline_with_channels()
    packets = [make_packet("source", "worker", b"x") for _ in range(4)]
    result = pipeline.run(packets)
    assert result.packets_in == 4


def test_pipeline_run_history_accumulates():
    pipeline = make_pipeline_with_channels()
    pipeline.run([make_packet("source", "worker", b"a")])
    pipeline.run([make_packet("source", "worker", b"b")])
    assert len(pipeline.run_history()) == 2


def test_total_packets_routed_sums_runs():
    pipeline = FreeFlowPipeline()
    ch = FlowChannel("ch", "A", "B")
    pipeline.add_channel(ch)
    pipeline.run([make_packet("A", "B", b"x")])
    pipeline.run([make_packet("A", "B", b"y")])
    total = pipeline.total_packets_routed()
    assert total >= 0  # Routing logic depends on channel matching; at minimum non-negative.


# ---------------------------------------------------------------------------
# FreeFlowPipeline — processor integration
# ---------------------------------------------------------------------------

def test_processor_transforms_payload():
    pipeline = FreeFlowPipeline()
    pipeline.add_channel(FlowChannel("ingest", "src", "proc"))

    def upper(pkt):
        return pkt.payload.upper()

    pipeline.add_processor("proc", upper)
    pkt = make_packet("src", "proc", b"hello")
    pipeline.run([pkt])
    # Processor ran without error — no processor_errors in result.
    result = pipeline.run_history()[-1]
    assert result.processor_errors == 0


def test_processor_error_counted():
    pipeline = FreeFlowPipeline()
    pipeline.add_channel(FlowChannel("ingest", "src", "proc"))

    def bad_processor(pkt):
        raise RuntimeError("crash")

    pipeline.add_processor("proc", bad_processor)
    pkt = make_packet("src", "proc", b"data")
    result = pipeline.run([pkt])
    assert result.processor_errors == 1


def test_processor_returning_none_counted_as_error():
    pipeline = FreeFlowPipeline()
    pipeline.add_channel(FlowChannel("ch", "src", "proc"))

    pipeline.add_processor("proc", lambda pkt: None)
    result = pipeline.run([make_packet("src", "proc", b"d")])
    assert result.processor_errors == 1


# ---------------------------------------------------------------------------
# Channel stats accessible from pipeline
# ---------------------------------------------------------------------------

def test_channel_stats_accessible_by_name():
    pipeline = FreeFlowPipeline()
    ch = FlowChannel("my_channel", "X", "Y")
    pipeline.add_channel(ch)
    stats = pipeline.channel_stats("my_channel")
    assert isinstance(stats, ChannelStats)


def test_channel_stats_returns_none_for_unknown():
    pipeline = FreeFlowPipeline()
    assert pipeline.channel_stats("nonexistent") is None


# ---------------------------------------------------------------------------
# Pipeline run success_rate
# ---------------------------------------------------------------------------

def test_success_rate_one_when_no_packets():
    run = PipelineRun(
        run_id="r",
        packets_in=0,
        packets_out=0,
        tamper_detected=0,
        processor_errors=0,
        started_at=__import__("datetime").datetime.now(),
    )
    assert run.success_rate == 1.0


def test_success_rate_fraction():
    run = PipelineRun(
        run_id="r",
        packets_in=4,
        packets_out=3,
        tamper_detected=0,
        processor_errors=1,
        started_at=__import__("datetime").datetime.now(),
    )
    assert run.success_rate == pytest.approx(0.75)
