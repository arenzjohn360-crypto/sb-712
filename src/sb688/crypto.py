"""
SB688 Encryption layer — AES-256-GCM.

Every write is encrypted with a fresh 96-bit nonce.  The GCM
authentication tag is stored alongside the ciphertext so any
corruption or tampering raises EncryptionError on read — there is
no path by which a corrupt ciphertext silently decrypts to garbage.

Key rotation is supported: the active key ID (2 bytes) is prepended to
every ciphertext blob so the right key is used for decryption regardless
of when a record was written.
"""
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12   # 96-bit nonce for GCM
KEY_ID_SIZE = 2   # bytes — supports up to 65 535 rotations


class EncryptionError(Exception):
    """Raised when decryption or authentication fails."""


class EncryptedStore:
    """
    Transparent AES-256-GCM encryption wrapper around any store that
    exposes put(key, bytes) / get(key) / delete(key).

    Supports key rotation: call rotate_key() to generate and activate a
    new key.  Existing records remain readable with their original key.
    """

    def __init__(self, store, key: Optional[bytes] = None) -> None:
        self._store = store
        self._active_key_id = 0
        self._keys: dict[int, bytes] = {
            0: key if key is not None else AESGCM.generate_key(bit_length=256)
        }

    # ------------------------------------------------------------------ #
    #  Key management                                                      #
    # ------------------------------------------------------------------ #

    @property
    def _active_key(self) -> bytes:
        return self._keys[self._active_key_id]

    def rotate_key(self) -> int:
        """Generate and activate a new 256-bit key.  Returns new key ID."""
        new_id = max(self._keys) + 1
        self._keys[new_id] = AESGCM.generate_key(bit_length=256)
        self._active_key_id = new_id
        return new_id

    # ------------------------------------------------------------------ #
    #  Encryption helpers                                                  #
    # ------------------------------------------------------------------ #

    def _encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(NONCE_SIZE)
        aesgcm = AESGCM(self._active_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        key_id_bytes = self._active_key_id.to_bytes(KEY_ID_SIZE, "big")
        return key_id_bytes + nonce + ciphertext

    def _decrypt(self, blob: bytes) -> bytes:
        key_id = int.from_bytes(blob[:KEY_ID_SIZE], "big")
        if key_id not in self._keys:
            raise EncryptionError(f"Unknown key ID {key_id}")
        nonce = blob[KEY_ID_SIZE: KEY_ID_SIZE + NONCE_SIZE]
        ciphertext = blob[KEY_ID_SIZE + NONCE_SIZE:]
        aesgcm = AESGCM(self._keys[key_id])
        try:
            return aesgcm.decrypt(nonce, ciphertext, None)
        except Exception as exc:
            raise EncryptionError(
                f"Decryption / authentication failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    #  Store API                                                           #
    # ------------------------------------------------------------------ #

    def put(self, key: str, plaintext: bytes) -> None:
        self._store.put(key, self._encrypt(plaintext))

    def get(self, key: str) -> bytes:
        blob = self._store.get(key)
        return self._decrypt(blob)

    def delete(self, key: str) -> None:
        self._store.delete(key)

    def inject_corruption(self, key: str, byte_offset: int = KEY_ID_SIZE + NONCE_SIZE + 1) -> None:
        """Corrupt the ciphertext payload (skips key-id + nonce by default)."""
        self._store.inject_bit_flip(key, byte_offset)

    def __len__(self) -> int:
        return len(self._store)
