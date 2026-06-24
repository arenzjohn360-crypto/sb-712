"""
SB688 Merkle Tree — immutability proofs.

Builds a balanced binary Merkle tree over an ordered dictionary of
(key, value) pairs.  Provides:

- root hash — a single fingerprint of the entire dataset.
- proof(key) — a list of (direction, sibling_hash) tuples.
- verify_proof(key, value, proof, root) — static verifier.

Any modification to any value changes the root hash and invalidates
every proof derived from the original root.
"""
import hashlib
from typing import Dict, List, Optional, Tuple


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _combine(left: bytes, right: bytes) -> bytes:
    return _sha256(left + right)


class MerkleTree:
    """
    Immutable Merkle tree.  Construct once from a snapshot of data; use
    proof() / verify_proof() to prove membership and integrity.
    """

    def __init__(self, items: Dict[str, bytes]) -> None:
        # Deterministic leaf ordering
        self._items = dict(sorted(items.items()))
        self._keys: List[str] = list(self._items.keys())
        self._leaves: List[bytes] = [
            _sha256(k.encode() + v) for k, v in self._items.items()
        ]
        self._tree: List[List[bytes]] = self._build(self._leaves)

    # ------------------------------------------------------------------ #
    #  Tree construction                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build(leaves: List[bytes]) -> List[List[bytes]]:
        if not leaves:
            return [[_sha256(b"")]]
        level = list(leaves)
        tree = [level]
        while len(level) > 1:
            if len(level) % 2:
                level = level + [level[-1]]  # duplicate last leaf if odd
            level = [
                _combine(level[i], level[i + 1])
                for i in range(0, len(level), 2)
            ]
            tree.append(level)
        return tree

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    @property
    def root(self) -> bytes:
        return self._tree[-1][0]

    def proof(self, key: str) -> Optional[List[Tuple[str, bytes]]]:
        """
        Return the Merkle proof for *key* as a list of
        (direction, sibling_hash) tuples, where direction is 'L' or 'R'.
        Returns None when *key* is not in the tree.
        """
        if key not in self._keys:
            return None
        idx = self._keys.index(key)
        path: List[Tuple[str, bytes]] = []
        for level in self._tree[:-1]:
            # Pad odd levels the same way as _build
            padded = level if len(level) % 2 == 0 else level + [level[-1]]
            if idx % 2 == 0:
                sibling_idx = min(idx + 1, len(padded) - 1)
                direction = "R"
            else:
                sibling_idx = idx - 1
                direction = "L"
            path.append((direction, padded[sibling_idx]))
            idx //= 2
        return path

    @staticmethod
    def verify_proof(
        key: str,
        value: bytes,
        proof: List[Tuple[str, bytes]],
        root: bytes,
    ) -> bool:
        """Verify a Merkle proof without reconstructing the whole tree."""
        current = _sha256(key.encode() + value)
        for direction, sibling in proof:
            if direction == "R":
                current = _combine(current, sibling)
            else:
                current = _combine(sibling, current)
        return current == root
