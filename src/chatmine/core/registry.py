from __future__ import annotations

from .provider import Provider

_REGISTRY: dict[str, Provider] = {}


def register(provider: Provider) -> Provider:
    """Registra um provider pelo seu `.name`. Usado na importação do módulo."""
    _REGISTRY[provider.name] = provider
    return provider


def get(name: str) -> Provider:
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(names()) or "(nenhum)"
        raise KeyError(f"Provider {name!r} não registrado. Disponíveis: {available}") from None


def names() -> list[str]:
    return sorted(_REGISTRY)
