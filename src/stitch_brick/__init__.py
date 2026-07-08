"""
SB-712 Stitch Brick — validation framework.

Public surface:
  BrickModule, BrickState, BrickOutput
  StrandChannel, MessageEnvelope
  ProtectedSpine, SpineVerificationError
  BraidOrchestrator, VerificationGate
  FaultInjector
  MetricsCollector, SingleRunResult, BatchMetrics
  ValidationRunner, SCENARIOS
  ProofGenerator
"""
from .brick import BrickModule, BrickState, BrickOutput
from .strand import StrandChannel, MessageEnvelope
from .spine import ProtectedSpine, SpineVerificationError, VERIFY_PASSES_REQUIRED
from .braid import BraidOrchestrator, VerificationGate
from .fault_injector import FaultInjector, FAULT_SCENARIOS
from .metrics import MetricsCollector, SingleRunResult, BatchMetrics
from .validator import ValidationRunner, SCENARIOS
from .proof_generator import ProofGenerator

__all__ = [
    "BrickModule",
    "BrickState",
    "BrickOutput",
    "StrandChannel",
    "MessageEnvelope",
    "ProtectedSpine",
    "SpineVerificationError",
    "VERIFY_PASSES_REQUIRED",
    "BraidOrchestrator",
    "VerificationGate",
    "FaultInjector",
    "FAULT_SCENARIOS",
    "MetricsCollector",
    "SingleRunResult",
    "BatchMetrics",
    "ValidationRunner",
    "SCENARIOS",
    "ProofGenerator",
]
