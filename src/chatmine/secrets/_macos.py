from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PBKDF2_SALT = b"saltysalt"
PBKDF2_ITER = 1003
AES_KEY_LEN = 16
IV = b" " * 16  # convenção v10 do Chromium/macOS


class BackendError(RuntimeError):
    pass


def _keychain_password(service: str) -> bytes:
    if shutil.which("security") is None:
        raise BackendError("/usr/bin/security não encontrado — é macOS mesmo?")
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", service],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        raise BackendError(
            f"Keychain: não consegui ler {service!r}. "
            f"Prompt do macOS foi cancelado? Detalhe: {stderr}"
        ) from e
    pw = out.stdout.rstrip("\n").encode("utf-8")
    if not pw:
        raise BackendError(
            f"Keychain: entrada {service!r} retornou vazio. "
            f"Abra o app, autentique e tente novamente."
        )
    return pw


@lru_cache(maxsize=4)
def get_master_key(service: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=AES_KEY_LEN,
        salt=PBKDF2_SALT,
        iterations=PBKDF2_ITER,
    )
    return kdf.derive(_keychain_password(service))


def decrypt_cookie(encrypted: bytes, key: bytes) -> bytes:
    if not encrypted.startswith(b"v10"):
        raise BackendError(f"prefixo não suportado no macOS: {encrypted[:4]!r}")
    ct = encrypted[3:]
    if len(ct) % 16 != 0:
        raise BackendError(f"ciphertext não múltiplo de 16: {len(ct)}")
    cipher = Cipher(algorithms.AES(key), modes.CBC(IV))
    dec = cipher.decryptor()
    padded = dec.update(ct) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()
