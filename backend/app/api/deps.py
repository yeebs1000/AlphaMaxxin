"""Shared FastAPI dependencies. Tests override get_registry with fakes."""
from ..data.registry import ProviderRegistry, get_default_registry


def get_registry() -> ProviderRegistry:
    return get_default_registry()
