"""Xiaomi MiMo provider profile."""

from zermes.providers import register_provider
from zermes.providers.base import ProviderProfile

xiaomi = ProviderProfile(
    name="xiaomi",
    aliases=("mimo", "xiaomi-mimo"),
    env_vars=("XIAOMI_API_KEY",),
    base_url="https://api.xiaomimimo.com/v1",
)

register_provider(xiaomi)
