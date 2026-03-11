# -*- coding: utf-8 -*-
"""Central model registry for all AI providers.

Eliminates hardcoded model names across modules.  Model names can be
overridden at runtime via ``st.secrets["models"]`` without touching code.
"""

from __future__ import annotations

MODEL_REGISTRY: dict[str, dict[str, str]] = {
    "openai":  {"default": "gpt-4o-mini"},
    "claude":  {"default": "claude-sonnet-4-6"},
    "gemini":  {"default": "gemini-2.5-flash"},
}


def get_model_name(
    provider: str,
    models_config: dict | None = None,
) -> str:
    """Resolve the model name for *provider*.

    Priority:
      1. ``models_config[provider]``  (from ``st.secrets["models"]``)
      2. ``MODEL_REGISTRY[provider]["default"]``
    """
    provider = provider.lower()
    if models_config and provider in models_config:
        return str(models_config[provider])
    entry = MODEL_REGISTRY.get(provider)
    if entry:
        return entry["default"]
    raise KeyError(f"Unknown AI provider: {provider!r}")
