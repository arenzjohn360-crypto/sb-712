"""
SB688 Erasure Coding (ECC) — XOR-parity shard encoding.

Splits a payload into *k* equal data shards plus one XOR parity shard.
Any single missing or corrupt shard can be reconstructed from the
remaining k shards and the parity shard (analogous to RAID-5).

This provides forward error correction (FEC) suitable for deep-space
black-box recovery and long-term archival scenarios where one storage
medium may fail or degrade beyond repair.
"""
from typing import List, Optional, Tuple


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _xor_all(shards: List[bytes]) -> bytes:
    result = shards[0]
    for s in shards[1:]:
        result = _xor_bytes(result, s)
    return result


class ECCEncoder:
    """
    XOR-parity erasure encoder / decoder.

    encode(data) → (data_shards, parity_shard)
    decode(shards, parity) → original data   (pass None for missing shard)

    The original data length is embedded in the payload so padding bytes
    added to reach an equal shard size are stripped on decode.
    """

    def __init__(self, k: int = 4) -> None:
        if k < 2:
            raise ValueError("k must be >= 2")
        self._k = k

    def encode(self, data: bytes) -> Tuple[List[bytes], bytes]:
        """
        Return (data_shards, parity_shard).

        The first 8 bytes of the payload encode the original data length
        so that padding can be stripped during decode.
        """
        length_prefix = len(data).to_bytes(8, "big")
        payload = length_prefix + data

        # Pad payload so it splits evenly into k shards
        remainder = len(payload) % self._k
        if remainder:
            payload += b"\x00" * (self._k - remainder)

        chunk = len(payload) // self._k
        shards = [payload[i * chunk: (i + 1) * chunk] for i in range(self._k)]
        parity = _xor_all(shards)
        return shards, parity

    def decode(
        self,
        shards: List[Optional[bytes]],
        parity: bytes,
    ) -> bytes:
        """
        Reconstruct original data.  Pass *None* for any missing shard.
        Raises ValueError if more than one shard is None.
        """
        missing = [i for i, s in enumerate(shards) if s is None]
        if len(missing) > 1:
            raise ValueError(
                f"Cannot recover: {len(missing)} shards missing (maximum 1)"
            )
        working = list(shards)
        if len(missing) == 1:
            idx = missing[0]
            known = [s for s in working if s is not None]
            recovered = _xor_bytes(parity, _xor_all(known))
            working[idx] = recovered

        payload = b"".join(working)  # type: ignore[arg-type]
        length = int.from_bytes(payload[:8], "big")
        return payload[8: 8 + length]

    def verify_shards(self, shards: List[bytes], parity: bytes) -> bool:
        """Return True if all shards are consistent with the parity shard."""
        if any(s is None for s in shards):
            return False
        return _xor_all(shards) == parity  # type: ignore[arg-type]
