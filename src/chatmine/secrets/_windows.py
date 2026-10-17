from __future__ import annotations

import base64
import ctypes
import json
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class BackendError(RuntimeError):
    pass


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _dpapi_unprotect(data: bytes) -> bytes:
    """Chama Win32 CryptUnprotectData num blob DPAPI de escopo de usuário."""
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL

    buf = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    in_blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        err = ctypes.get_last_error()
        raise BackendError(
            f"CryptUnprotectData falhou (WinError {err}). "
            f"Rodando sob o mesmo usuário que logou no app?"
        )
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


@lru_cache(maxsize=4)
def get_master_key(local_state_path: Path) -> bytes:
    ls = Path(local_state_path)
    if not ls.exists():
        raise BackendError(f"Local State não encontrado: {ls}")
    data = json.loads(ls.read_text(encoding="utf-8"))
    os_crypt = data.get("os_crypt") or {}
    enc_key_b64 = os_crypt.get("encrypted_key")
    app_bound = os_crypt.get("app_bound_encrypted_key")
    if not enc_key_b64:
        if app_bound:
            raise BackendError(
                "Este perfil usa app-bound encryption (v20). Para decriptar "
                "a chave seria necessário executar como SYSTEM (ex.: "
                "`psexec -s -i`). Alternativa: rode logado no mesmo usuário "
                "do app e SEM app-bound, ou use SharpChromium/DonPAPI "
                "externamente para despejar a chave."
            )
        raise BackendError("Local State não contém os_crypt.encrypted_key — formato desconhecido.")
    raw = base64.b64decode(enc_key_b64)
    if raw[:5] != b"DPAPI":
        raise BackendError(f"Prefixo inesperado em encrypted_key: {raw[:5]!r}")
    key = _dpapi_unprotect(raw[5:])
    if len(key) != 32:
        raise BackendError(
            f"Master key com tamanho inesperado: {len(key)} bytes (esperado 32 p/ AES-256-GCM)"
        )
    return key


def decrypt_cookie(encrypted: bytes, key: bytes) -> bytes:
    if encrypted.startswith(b"v20"):
        raise BackendError(
            "Cookie v20 (app-bound) detectado. Ver orientação em get_master_key() — "
            "precisa rodar como SYSTEM."
        )
    if not encrypted.startswith(b"v10"):
        raise BackendError(f"prefixo não suportado no Windows: {encrypted[:4]!r}")
    # Layout v10 (Windows): [3 prefix][12 nonce][ciphertext][16 tag]
    nonce = encrypted[3:15]
    ct_and_tag = encrypted[15:]
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ct_and_tag, associated_data=None)
    except Exception as e:  # cryptography levanta InvalidTag
        raise BackendError(f"AES-GCM falhou: {e}") from e
