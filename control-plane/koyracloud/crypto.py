"""Symmetric encryption for secrets at rest (Fernet)."""
from __future__ import annotations

from cryptography.fernet import Fernet


def generate_key() -> str:
    """A fresh urlsafe-base64 Fernet key."""
    return Fernet.generate_key().decode()


class CryptoBox:
    """Encrypt/decrypt secret values with a Fernet key.

    The key comes from ``KOYRA_SECRET_KEY``. In local dev, if it is empty an
    ephemeral key is generated (secrets won't survive a restart) and the caller
    is expected to warn.
    """

    def __init__(self, key: str):
        self._ephemeral = not key
        self._fernet = Fernet(key.encode() if key else Fernet.generate_key())

    @property
    def ephemeral(self) -> bool:
        return self._ephemeral

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()
