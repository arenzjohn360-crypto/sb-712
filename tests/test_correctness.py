"""
Correctness tests — data written must be returned bit-for-bit identical.

Covers:
- Arbitrary sizes (1 B → 64 MiB)
- Binary edge-case patterns (all-zeros, all-ones, repeating bytes)
- Single and double bit-flip detection
- Overwrite / version tracking
- Missing-key behaviour
- 10 000-key bulk round-trip
"""
import os
import pytest
from sb688 import BlockStore, CorruptionError


# ------------------------------------------------------------------ #
#  Round-trip correctness                                              #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("size", [1, 7, 255, 256, 4096, 65_536, 1_048_576])
def test_write_read_exact(size):
    """Data written must be returned exactly as written (bit-for-bit)."""
    store = BlockStore()
    data = os.urandom(size)
    store.put(f"key_{size}", data)
    assert store.get(f"key_{size}") == data


def test_all_zero_bytes():
    store = BlockStore()
    store.put("zeros", b"\x00" * 4096)
    assert store.get("zeros") == b"\x00" * 4096


def test_all_ones_bytes():
    store = BlockStore()
    store.put("ones", b"\xff" * 4096)
    assert store.get("ones") == b"\xff" * 4096


@pytest.mark.parametrize("pattern", [
    bytes(range(256)) * 16,
    b"\xde\xad\xbe\xef" * 1024,
    b"\xca\xfe\xba\xbe" * 512,
])
def test_binary_patterns(pattern):
    store = BlockStore()
    store.put("pat", pattern)
    assert store.get("pat") == pattern


def test_empty_value():
    store = BlockStore()
    store.put("empty", b"")
    assert store.get("empty") == b""


def test_unicode_key():
    store = BlockStore()
    store.put("日本語キー", b"data")
    assert store.get("日本語キー") == b"data"


@pytest.mark.timeout(30)
def test_large_64mb_value():
    store = BlockStore()
    data = os.urandom(64 * 1024 * 1024)
    store.put("large", data)
    assert store.get("large") == data


# ------------------------------------------------------------------ #
#  Corruption detection                                                #
# ------------------------------------------------------------------ #

def test_single_bit_flip_detected():
    store = BlockStore()
    data = os.urandom(64)
    store.put("key", data)
    store.inject_bit_flip("key", byte_offset=10, bit=3)
    with pytest.raises(CorruptionError):
        store.get("key")


def test_double_bit_flip_detected():
    store = BlockStore()
    store.put("key", os.urandom(64))
    store.inject_bit_flip("key", byte_offset=5, bit=1)
    store.inject_bit_flip("key", byte_offset=20, bit=7)
    with pytest.raises(CorruptionError):
        store.get("key")


def test_full_data_replacement_detected():
    store = BlockStore()
    store.put("key", b"original")
    store.inject_corrupt_data("key", b"GARBAGE_BYTES_REPLACING_PAYLOAD")
    with pytest.raises(CorruptionError):
        store.get("key")


# ------------------------------------------------------------------ #
#  Overwrite / version tracking                                        #
# ------------------------------------------------------------------ #

def test_overwrite_returns_new_value():
    store = BlockStore()
    store.put("key", b"version1")
    store.put("key", b"version2")
    assert store.get("key") == b"version2"


def test_version_increments_on_overwrite():
    store = BlockStore()
    for i in range(5):
        store.put("key", f"v{i}".encode())
        assert store.get_version("key") == i


# ------------------------------------------------------------------ #
#  Key management                                                      #
# ------------------------------------------------------------------ #

def test_delete_removes_key():
    store = BlockStore()
    store.put("key", b"data")
    store.delete("key")
    with pytest.raises(KeyError):
        store.get("key")


def test_missing_key_raises_key_error():
    store = BlockStore()
    with pytest.raises(KeyError):
        store.get("nonexistent")


# ------------------------------------------------------------------ #
#  Bulk                                                                #
# ------------------------------------------------------------------ #

def test_10k_keys_all_correct():
    store = BlockStore()
    items = {f"key_{i:05d}": os.urandom(64) for i in range(10_000)}
    for k, v in items.items():
        store.put(k, v)
    for k, v in items.items():
        assert store.get(k) == v


def test_verify_all_clean_store():
    store = BlockStore()
    for i in range(200):
        store.put(f"k{i}", os.urandom(32))
    assert store.corrupt_keys() == []


def test_verify_all_detects_multiple_corruptions():
    store = BlockStore()
    for i in range(20):
        store.put(f"k{i}", os.urandom(32))
    corrupt_targets = {"k3", "k7", "k15"}
    for k in corrupt_targets:
        store.inject_bit_flip(k, 0)
    assert set(store.corrupt_keys()) == corrupt_targets
