"""Japanese-RP-Bench public API.

Legacy helpers are loaded lazily so the provider-neutral v2 tooling does not
require inference dependencies such as datasets, transformers, or vLLM.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_LAZY_EXPORTS = {
    "load_dataset_wrapper": ("japanese_rp_bench.data", "load_dataset_wrapper"),
    "evaluate_conversation": ("japanese_rp_bench.evaluation", "evaluate_conversation"),
    "generate_response": ("japanese_rp_bench.models", "generate_response"),
    "load_model": ("japanese_rp_bench.models", "load_model"),
    "construct_system_prompts": ("japanese_rp_bench.prompts", "construct_system_prompts"),
    "run_eval": ("japanese_rp_bench.run", "run_eval"),
    "extract_and_escape_json_string": (
        "japanese_rp_bench.utils",
        "extract_and_escape_json_string",
    ),
    "is_valid_evaluation": ("japanese_rp_bench.utils", "is_valid_evaluation"),
    "setup_logging": ("japanese_rp_bench.utils", "setup_logging"),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
