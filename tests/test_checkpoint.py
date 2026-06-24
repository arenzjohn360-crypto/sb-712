from datetime import datetime, timedelta
from sb_712.checkpoint import Checkpoint, CheckpointRegistry, CheckpointStatus


def make_checkpoint(
    project_id="PRJ-001",
    status=CheckpointStatus.HEALTHY,
    certified=True,
    **kwargs,
):
    return Checkpoint(project_id=project_id, status=status, certified=certified, **kwargs)


# ---------------------------------------------------------------------------
# get_last_healthy_certified
# ---------------------------------------------------------------------------

def test_get_last_healthy_certified_returns_most_recent():
    registry = CheckpointRegistry()
    old = make_checkpoint()
    old.created_at = datetime(2024, 1, 1)
    new = make_checkpoint()
    new.created_at = datetime(2024, 6, 1)
    registry.add_checkpoint(old)
    registry.add_checkpoint(new)
    assert registry.get_last_healthy_certified("PRJ-001") is new


def test_get_last_healthy_certified_none_when_empty():
    registry = CheckpointRegistry()
    assert registry.get_last_healthy_certified("NO-PROJECT") is None


def test_get_last_healthy_certified_ignores_uncertified():
    registry = CheckpointRegistry()
    registry.add_checkpoint(make_checkpoint(certified=False))
    assert registry.get_last_healthy_certified("PRJ-001") is None


def test_get_last_healthy_certified_ignores_corrupted():
    registry = CheckpointRegistry()
    registry.add_checkpoint(make_checkpoint(status=CheckpointStatus.CORRUPTED))
    assert registry.get_last_healthy_certified("PRJ-001") is None


def test_get_last_healthy_certified_ignores_degraded():
    registry = CheckpointRegistry()
    registry.add_checkpoint(make_checkpoint(status=CheckpointStatus.DEGRADED))
    assert registry.get_last_healthy_certified("PRJ-001") is None


def test_get_last_healthy_certified_ignores_other_projects():
    registry = CheckpointRegistry()
    registry.add_checkpoint(make_checkpoint(project_id="PRJ-OTHER"))
    assert registry.get_last_healthy_certified("PRJ-001") is None


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------

def test_rollback_success():
    registry = CheckpointRegistry()
    cp = make_checkpoint()
    registry.add_checkpoint(cp)
    result = registry.rollback("PRJ-001", reason="test rollback")
    assert result.success is True
    assert result.checkpoint_id == cp.checkpoint_id
    assert "PRJ-001" in result.message


def test_rollback_fails_no_checkpoint():
    registry = CheckpointRegistry()
    result = registry.rollback("MISSING-PROJECT")
    assert result.success is False
    assert result.checkpoint_id is None


def test_rollback_records_reason():
    registry = CheckpointRegistry()
    registry.add_checkpoint(make_checkpoint())
    result = registry.rollback("PRJ-001", reason="spine threatened")
    assert result.reason == "spine threatened"


# ---------------------------------------------------------------------------
# all_checkpoints
# ---------------------------------------------------------------------------

def test_all_checkpoints_no_filter():
    registry = CheckpointRegistry()
    registry.add_checkpoint(make_checkpoint("PRJ-A"))
    registry.add_checkpoint(make_checkpoint("PRJ-B"))
    assert len(registry.all_checkpoints()) == 2


def test_all_checkpoints_filter_by_project():
    registry = CheckpointRegistry()
    registry.add_checkpoint(make_checkpoint("PRJ-A"))
    registry.add_checkpoint(make_checkpoint("PRJ-B"))
    assert len(registry.all_checkpoints("PRJ-A")) == 1
