"""Small HTTP adapters for provider-neutral benchmark execution.

Credentials are read only from environment variables and are never included in
artifacts, exceptions, or logs.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Sequence

from japanese_rp_bench.v2.schemas import SchemaError


class ProviderError(RuntimeError):
    """Raised when a model provider request cannot be completed safely."""


class RateLimitError(ProviderError):
    """Raised when a provider quota or rate window has been exhausted."""


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    model: str
    api_key_env: str
    reasoning: str
    input_price_per_million: float
    output_price_per_million: float
    api_style: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelSpec":
        required = (
            "id",
            "provider",
            "model",
            "api_key_env",
            "reasoning",
            "input_price_per_million",
            "output_price_per_million",
        )
        missing = [key for key in required if key not in data]
        if missing:
            raise SchemaError(f"Model spec is missing: {', '.join(missing)}")
        provider = str(data["provider"])
        if provider not in {"openai", "gemini", "anthropic", "opencode_go"}:
            raise SchemaError(f"Unsupported provider: {provider}")
        api_style = str(data.get("api_style", ""))
        if provider == "opencode_go" and api_style not in {
            "openai_chat",
            "anthropic_messages",
        }:
            raise SchemaError(
                "OpenCode Go model spec requires api_style: "
                "openai_chat or anthropic_messages"
            )
        return cls(
            id=str(data["id"]),
            provider=provider,
            model=str(data["model"]),
            api_key_env=str(data["api_key_env"]),
            reasoning=str(data["reasoning"]),
            input_price_per_million=float(data["input_price_per_million"]),
            output_price_per_million=float(data["output_price_per_million"]),
            api_style=api_style,
        )


@dataclass(frozen=True)
class GenerationResult:
    text: str
    requested_model: str
    resolved_model: str
    provider: str
    response_id: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def generate_text(
    spec: ModelSpec,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool = False,
    json_schema: Mapping[str, Any] | None = None,
) -> GenerationResult:
    api_key = os.environ.get(spec.api_key_env)
    if not api_key:
        raise ProviderError(f"Required environment variable is not set: {spec.api_key_env}")
    attempts = 1 if spec.provider in {"gemini", "anthropic"} else 3
    for attempt in range(1, attempts + 1):
        try:
            if spec.provider == "openai":
                return _generate_openai(spec, api_key, system_prompt, messages, max_output_tokens)
            if spec.provider == "anthropic":
                return _generate_anthropic(
                    spec,
                    api_key,
                    system_prompt,
                    messages,
                    max_output_tokens,
                    json_mode,
                    json_schema,
                )
            if spec.provider == "opencode_go":
                if spec.api_style == "openai_chat":
                    return _generate_opencode_go_chat(
                        spec,
                        api_key,
                        system_prompt,
                        messages,
                        max_output_tokens,
                        json_mode,
                    )
                return _generate_opencode_go_anthropic(
                    spec,
                    api_key,
                    system_prompt,
                    messages,
                    max_output_tokens,
                    json_mode,
                    json_schema,
                )
            return _generate_gemini(
                spec,
                api_key,
                system_prompt,
                messages,
                max_output_tokens,
                json_mode,
                json_schema,
            )
        except RateLimitError:
            raise
        except ProviderError:
            if attempt == attempts:
                raise
            time.sleep(min(2 ** (attempt - 1), 4))
    raise ProviderError("Provider generation failed after retries")


def estimated_list_cost(spec: ModelSpec, result: GenerationResult) -> float:
    return (
        result.input_tokens * spec.input_price_per_million
        + result.output_tokens * spec.output_price_per_million
    ) / 1_000_000


def _generate_openai(
    spec: ModelSpec,
    api_key: str,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
) -> GenerationResult:
    payload: Dict[str, Any] = {
        "model": spec.model,
        "instructions": system_prompt,
        "input": [
            {"role": item["role"], "content": item["content"]}
            for item in messages
        ],
        "max_output_tokens": max_output_tokens,
        "store": False,
    }
    if spec.reasoning:
        payload["reasoning"] = {"effort": spec.reasoning}
    response = _post_json(
        "https://api.openai.com/v1/responses",
        payload,
        {"Authorization": f"Bearer {api_key}"},
    )
    if response.get("error"):
        raise ProviderError(f"OpenAI API error: {_safe_error(response['error'])}")
    text_parts = []
    for output in response.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                text_parts.append(str(content["text"]))
    text = "\n".join(text_parts).strip()
    if not text:
        raise ProviderError("OpenAI response did not contain output text")
    usage = response.get("usage") or {}
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    return GenerationResult(
        text=text,
        requested_model=spec.id,
        resolved_model=str(response.get("model", spec.model)),
        provider=spec.provider,
        response_id=str(response.get("id", "")),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        reasoning_tokens=int(output_details.get("reasoning_tokens", 0)),
        cached_input_tokens=int(input_details.get("cached_tokens", 0)),
    )


def _generate_gemini(
    spec: ModelSpec,
    api_key: str,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool,
    json_schema: Mapping[str, Any] | None,
) -> GenerationResult:
    generation_config: Dict[str, Any] = {
        "maxOutputTokens": max_output_tokens,
        "thinkingConfig": {"thinkingLevel": spec.reasoning},
    }
    if json_mode:
        generation_config["responseMimeType"] = "application/json"
    if json_schema is not None:
        generation_config["responseSchema"] = _without_schema_keywords(
            json_schema,
            {
                "additionalProperties",
                "enum",
                "maximum",
                "maxItems",
                "minimum",
                "minItems",
            },
        )
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in messages
        ],
        "generationConfig": generation_config,
    }
    response = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{spec.model}:generateContent",
        payload,
        {"x-goog-api-key": api_key},
        attempts=1,
    )
    if response.get("error"):
        raise ProviderError(f"Gemini API error: {_safe_error(response['error'])}")
    text_parts = []
    for candidate in response.get("candidates", []):
        for part in (candidate.get("content") or {}).get("parts", []):
            if part.get("text") and not part.get("thought", False):
                text_parts.append(str(part["text"]))
    text = "\n".join(text_parts).strip()
    if not text:
        finish_reasons = [item.get("finishReason") for item in response.get("candidates", [])]
        raise ProviderError(f"Gemini response did not contain output text: {finish_reasons}")
    usage = response.get("usageMetadata") or {}
    reasoning_tokens = int(usage.get("thoughtsTokenCount", 0))
    output_tokens = int(usage.get("candidatesTokenCount", 0)) + reasoning_tokens
    return GenerationResult(
        text=text,
        requested_model=spec.id,
        resolved_model=str(response.get("modelVersion", spec.model)),
        provider=spec.provider,
        response_id=str(response.get("responseId", "")),
        input_tokens=int(usage.get("promptTokenCount", 0)),
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cached_input_tokens=int(usage.get("cachedContentTokenCount", 0)),
    )


def _generate_anthropic(
    spec: ModelSpec,
    api_key: str,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool,
    json_schema: Mapping[str, Any] | None,
) -> GenerationResult:
    return _generate_anthropic_messages(
        spec,
        api_key,
        system_prompt,
        messages,
        max_output_tokens,
        json_mode,
        json_schema,
        url="https://api.anthropic.com/v1/messages",
        provider_name="Anthropic",
    )


def _generate_opencode_go_anthropic(
    spec: ModelSpec,
    api_key: str,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool,
    json_schema: Mapping[str, Any] | None = None,
) -> GenerationResult:
    return _generate_anthropic_messages(
        spec,
        api_key,
        system_prompt,
        messages,
        max_output_tokens,
        json_mode,
        json_schema,
        url="https://opencode.ai/zen/go/v1/messages",
        provider_name="OpenCode Go",
    )


def _generate_anthropic_messages(
    spec: ModelSpec,
    api_key: str,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool,
    json_schema: Mapping[str, Any] | None,
    *,
    url: str,
    provider_name: str,
) -> GenerationResult:
    system = system_prompt
    if json_mode:
        system += "\n\nReturn only one valid JSON object without Markdown fences or commentary."
    payload: Dict[str, Any] = {
        "model": spec.model,
        "system": system,
        "messages": [
            {"role": item["role"], "content": item["content"]}
            for item in messages
        ],
        "max_tokens": max_output_tokens,
    }
    if spec.reasoning not in {"", "none", "minimal"}:
        payload["thinking"] = {"type": "enabled", "budget_tokens": 1024}
    if json_schema is not None:
        payload["output_config"] = {
            "format": {
                "type": "json_schema",
                "schema": _without_schema_keywords(
                    json_schema,
                    {"maximum", "maxItems", "minimum", "minItems"},
                ),
            }
        }
    response = _post_json(
        url,
        payload,
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        attempts=1 if spec.provider == "anthropic" else 4,
    )
    if response.get("error"):
        raise ProviderError(f"{provider_name} API error: {_safe_error(response['error'])}")
    text = "\n".join(
        str(block["text"])
        for block in response.get("content", [])
        if block.get("type") == "text" and block.get("text")
    ).strip()
    if not text:
        raise ProviderError(
            f"Anthropic response did not contain output text: {response.get('stop_reason')}"
        )
    usage = response.get("usage") or {}
    return GenerationResult(
        text=text,
        requested_model=spec.id,
        resolved_model=str(response.get("model", spec.model)),
        provider=spec.provider,
        response_id=str(response.get("id", "")),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cached_input_tokens=int(usage.get("cache_read_input_tokens", 0)),
    )


def _generate_opencode_go_chat(
    spec: ModelSpec,
    api_key: str,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool,
) -> GenerationResult:
    system = system_prompt
    if json_mode:
        system += "\n\nReturn only one valid JSON object without Markdown fences or commentary."
    payload: Dict[str, Any] = {
        "model": spec.model,
        "messages": [
            {"role": "system", "content": system},
            *[
                {"role": item["role"], "content": item["content"]}
                for item in messages
            ],
        ],
        "max_tokens": max_output_tokens,
        "stream": False,
    }
    response = _post_json(
        "https://opencode.ai/zen/go/v1/chat/completions",
        payload,
        {"Authorization": f"Bearer {api_key}"},
    )
    if response.get("error"):
        raise ProviderError(f"OpenCode Go API error: {_safe_error(response['error'])}")
    choices = response.get("choices") or []
    message = choices[0].get("message", {}) if choices else {}
    content = message.get("content", "")
    if isinstance(content, list):
        text = "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, Mapping) and part.get("text")
        ).strip()
    elif content is None:
        text = ""
    else:
        text = str(content).strip()
    if not text:
        finish_reasons = [item.get("finish_reason") for item in choices]
        raise ProviderError(
            f"OpenCode Go response did not contain output text: {finish_reasons}"
        )
    usage = response.get("usage") or {}
    input_details = usage.get("prompt_tokens_details") or {}
    output_details = usage.get("completion_tokens_details") or {}
    return GenerationResult(
        text=text,
        requested_model=spec.id,
        resolved_model=str(response.get("model", spec.model)),
        provider=spec.provider,
        response_id=str(response.get("id", "")),
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
        reasoning_tokens=int(output_details.get("reasoning_tokens", 0)),
        cached_input_tokens=int(input_details.get("cached_tokens", 0)),
    )


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    attempts: int = 4,
) -> Dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {
        "Content-Type": "application/json",
        "User-Agent": "Japanese-RP-Bench-v2/0.1",
        **headers,
    }
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, data=encoded, headers=request_headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                value = json.loads(response.read().decode("utf-8"))
                if not isinstance(value, dict):
                    raise ProviderError("Provider response JSON root is not an object")
                return value
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                raise RateLimitError(
                    f"Provider HTTP 429: {_safe_error_body(body)}"
                ) from exc
            retryable = 500 <= exc.code < 600
            if not retryable or attempt == attempts:
                raise ProviderError(
                    f"Provider HTTP {exc.code}: {_safe_error_body(body)}"
                ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts:
                raise ProviderError(f"Provider request failed: {type(exc).__name__}") from exc
        time.sleep(min(2 ** (attempt - 1), 8))
    raise ProviderError("Provider request failed after retries")


def _safe_error(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("message", value.get("status", "unknown error")))[:500]
    return str(value)[:500]


def _safe_error_body(body: str) -> str:
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return "non-JSON error response"
    if isinstance(value, Mapping):
        return _safe_error(value.get("error", value))
    return "unknown provider error"


def _without_schema_keywords(value: Any, excluded: set[str]) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_schema_keywords(item, excluded)
            for key, item in value.items()
            if key not in excluded
        }
    if isinstance(value, list):
        return [_without_schema_keywords(item, excluded) for item in value]
    return value
