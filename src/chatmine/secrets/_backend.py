from __future__ import annotations

import sys

from .vault import ChromiumVault

if sys.platform == "darwin":
    from . import _macos as _impl
elif sys.platform == "win32":
    from . import _windows as _impl
else:
    raise RuntimeError(
        f"Plataforma {sys.platform!r} não suportada. "
        f"Apenas macOS e Windows têm os apps Chromium nativos alvo."
    )

BackendError = _impl.BackendError
decrypt_cookie = _impl.decrypt_cookie


def get_master_key(vault: ChromiumVault) -> bytes:
    if sys.platform == "darwin":
        return _impl.get_master_key(vault.keychain_service)
    return _impl.get_master_key(vault.local_state())


__all__ = ["BackendError", "decrypt_cookie", "get_master_key"]
