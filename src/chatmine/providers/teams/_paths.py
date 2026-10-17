"""Localização dos arquivos do New Teams (v2) — específico do Teams."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _macos_root() -> Path:
    return (
        Path.home()
        / "Library/Containers/com.microsoft.teams2/Data/Library/"
        "Application Support/Microsoft/MSTeams"
    )


def _windows_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("%LOCALAPPDATA% não definido no ambiente")
    packages = Path(local) / "Packages"
    for pkg in sorted(packages.glob("MSTeams_*")):
        cache = pkg / "LocalCache" / "Microsoft" / "MSTeams"
        if cache.exists():
            return cache
    return packages / "MSTeams_8wekyb3d8bbwe" / "LocalCache" / "Microsoft" / "MSTeams"


def teams_root() -> Path:
    if sys.platform == "darwin":
        return _macos_root()
    if sys.platform == "win32":
        return _windows_root()
    raise RuntimeError(
        f"Plataforma {sys.platform!r} não suportada. "
        f"Apenas macOS ('darwin') e Windows ('win32') têm New Teams nativo."
    )


def ebwebview() -> Path:
    return teams_root() / "EBWebView"


def local_state() -> Path:
    return ebwebview() / "Local State"


def _profile_dir(profile: str) -> Path:
    if profile not in ("tfw", "tfl"):
        raise ValueError(f"profile deve ser 'tfw' ou 'tfl', recebi {profile!r}")
    return ebwebview() / f"WV2Profile_{profile}"


def cookie_dbs(profile: str | None) -> list[Path]:
    """Caminhos existentes do SQLite de cookies para o perfil (default 'tfw').

    Chromium novo guarda em Network/Cookies; builds antigos na raiz do perfil.
    """
    base = _profile_dir(profile or "tfw")
    found = [p for p in (base / "Network" / "Cookies", base / "Cookies") if p.exists()]
    if not found:
        raise FileNotFoundError(
            f"Cookies SQLite não encontrado para perfil {profile or 'tfw'!r} em {base}"
        )
    return found
