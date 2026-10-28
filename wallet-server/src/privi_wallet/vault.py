"""Password hashing and encryption of custodial private keys."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P).derive(password.encode("utf-8"))
    return "scrypt$%d$%s$%s" % (_SCRYPT_N, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, salt_b64, dk_b64 = stored.split("$")
        dk = Scrypt(salt=base64.b64decode(salt_b64), length=32, n=int(n), r=_SCRYPT_R, p=_SCRYPT_P).derive(
            password.encode("utf-8"))
    except Exception:
        return False
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class KeyVault:
    """AES-256-GCM encryption of private keys. The key is derived from WALLET_MASTER_KEY; each ciphertext is bound
    (as associated data) to the account and address it belongs to, so a stored key cannot be moved to another row."""

    VERSION = "v1"

    def __init__(self, master_key: str):
        if len(master_key) < 32:
            raise ValueError("WALLET_MASTER_KEY must be at least 32 characters")
        self._aes = AESGCM(hashlib.sha256(b"privi-wallet/key-encryption/v1|" + master_key.encode()).digest())

    @staticmethod
    def _aad(user_id: int, address: str) -> bytes:
        return f"privi-wallet|{user_id}|{address.lower()}".encode()

    def seal(self, private_key_hex: str, user_id: int, address: str) -> str:
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, bytes.fromhex(private_key_hex.removeprefix("0x")), self._aad(user_id, address))
        return f"{self.VERSION}:{base64.b64encode(nonce).decode()}:{base64.b64encode(ct).decode()}"

    def open(self, sealed: str, user_id: int, address: str) -> str:
        version, nonce_b64, ct_b64 = sealed.split(":")
        if version != self.VERSION:
            raise ValueError("unknown key format")
        pk = self._aes.decrypt(base64.b64decode(nonce_b64), base64.b64decode(ct_b64), self._aad(user_id, address))
        return "0x" + pk.hex()
