"""Shared pytest fixtures for the SB688 stress test suite."""
import pytest
from sb688 import BlockStore, DurableStore, EncryptedStore, ReplicaSet
from sb688.wal import WriteAheadLog


@pytest.fixture
def store():
    return BlockStore()


@pytest.fixture
def durable():
    inner = BlockStore()
    wal = WriteAheadLog()
    return DurableStore(store=inner, wal=wal)


@pytest.fixture
def replicas():
    return ReplicaSet(n=3, quorum=2)


@pytest.fixture
def enc_store():
    return EncryptedStore(BlockStore())
