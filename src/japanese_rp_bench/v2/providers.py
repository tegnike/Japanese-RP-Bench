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
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Sequence

from japanese_rp_bench.v2.schemas import SchemaError


class ProviderError(RuntimeError):
    """Raised when a model provider request cannot be completed safely."""


class RateLimitError(ProviderError):
    """Raised when a provider quota or rate window has been exhausted."""


class GenerationOutcomeError(ProviderError):
    """Raised for a terminal model outcome that must not enter scored artifacts."""

    def __init__(self, message: str, result: "GenerationResult") -> None:
        super().__init__(message)
        self.result = result


class IncompleteGenerationError(GenerationOutcomeError):
    """Raised when a provider explicitly reports an incomplete response."""


class TruncatedGenerationError(IncompleteGenerationError):
    """Raised when a provider reports that the output limit was reached."""


class BlockedGenerationError(GenerationOutcomeError):
    """Raised when refusal or safety filtering leaves no scorable response text."""


class FailedGenerationError(GenerationOutcomeError):
    """Raised when a provider returns a terminal failed response."""


class UnexpectedGenerationError(GenerationOutcomeError):
    """Raised when a provider omits or returns an unsupported termination reason."""


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
    batch: bool = False

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
        batch = bool(data.get("batch", False))
        if batch and provider not in {"openai", "gemini", "anthropic"}:
            raise SchemaError(
                "Batch execution is only supported for OpenAI, Gemini, and Anthropic models"
            )
        reasoning = str(data["reasoning"])
        _validate_reasoning_setting(
            provider,
            api_style,
            reasoning,
            model=str(data["model"]),
        )
        return cls(
            id=str(data["id"]),
            provider=provider,
            model=str(data["model"]),
            api_key_env=str(data["api_key_env"]),
            reasoning=reasoning,
            input_price_per_million=float(data["input_price_per_million"]),
            output_price_per_million=float(data["output_price_per_million"]),
            api_style=api_style,
            batch=batch,
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
    billing_mode: str = "standard"
    finish_reason: str = ""
    termination_category: str = "unknown"
    response_status: str = ""
    incomplete_reason: str = ""
    reasoning_config: Dict[str, Any] = field(default_factory=dict)
    requested_max_output_tokens: int = 0

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
                return _generate_openai(
                    spec,
                    api_key,
                    system_prompt,
                    messages,
                    max_output_tokens,
                    json_mode,
                    json_schema,
                )
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
        except (RateLimitError, GenerationOutcomeError):
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


def _validate_reasoning_setting(
    provider: str,
    api_style: str,
    reasoning: str,
    *,
    model: str = "",
) -> None:
    """Reject ambiguous or unsupported benchmark reasoning controls early."""
    if provider == "openai":
        allowed = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
    elif provider == "gemini":
        allowed = {"minimal", "low", "medium", "high"}
    elif provider == "anthropic" or (
        provider == "opencode_go" and api_style == "anthropic_messages"
    ):
        # Haiku 4.5 has no provider-native effort=low. The benchmark's abstract
        # low setting maps to the minimum manual thinking budget (1024 tokens).
        allowed = {"none", "low"}
    elif provider == "opencode_go" and api_style == "openai_chat":
        # These are the only values verified across the current Go candidates.
        allowed = {"none", "low"}
    else:
        raise SchemaError(
            f"Cannot validate reasoning for provider={provider}, api_style={api_style or 'default'}"
        )
    if reasoning not in allowed:
        choices = ", ".join(sorted(allowed))
        raise SchemaError(
            f"Unsupported reasoning setting {reasoning!r} for "
            f"provider={provider}, api_style={api_style or 'default'}; expected one of: {choices}"
        )
    if provider == "openai":
        model_allowed: set[str] | None = None
        if model.startswith("gpt-5.4-mini"):
            model_allowed = {"none", "low", "medium", "high", "xhigh"}
        elif model.startswith("gpt-5.6-sol"):
            model_allowed = {"none", "low", "medium", "high", "xhigh", "max"}
        if model_allowed is not None and reasoning not in model_allowed:
            choices = ", ".join(sorted(model_allowed))
            raise SchemaError(
                f"Unsupported reasoning setting {reasoning!r} for model={model}; "
                f"expected one of: {choices}"
            )


def _reasoning_request_config(spec: ModelSpec) -> Dict[str, Any]:
    """Return the exact provider request fragment recorded in result artifacts."""
    _validate_reasoning_setting(
        spec.provider,
        spec.api_style,
        spec.reasoning,
        model=spec.model,
    )
    if spec.provider == "openai":
        return {"reasoning": {"effort": spec.reasoning}}
    if spec.provider == "gemini":
        return {"thinkingConfig": {"thinkingLevel": spec.reasoning}}
    if spec.provider == "anthropic" or spec.api_style == "anthropic_messages":
        if spec.reasoning == "none":
            return {"thinking": {"type": "disabled"}}
        return {"thinking": {"type": "enabled", "budget_tokens": 1024}}
    return {"reasoning_effort": spec.reasoning}


def _generate_openai(
    spec: ModelSpec,
    api_key: str,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool,
    json_schema: Mapping[str, Any] | None,
) -> GenerationResult:
    payload = _build_openai_payload(
        spec,
        system_prompt,
        messages,
        max_output_tokens,
        json_mode,
        json_schema,
    )
    response = _post_json(
        "https://api.openai.com/v1/responses",
        payload,
        {"Authorization": f"Bearer {api_key}"},
    )
    if response.get("error"):
        raise ProviderError(f"OpenAI API error: {_safe_error(response['error'])}")
    return _parse_openai_response(
        spec,
        response,
        requested_max_output_tokens=max_output_tokens,
    )


def _build_openai_payload(
    spec: ModelSpec,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool = False,
    json_schema: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
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
    payload.update(_reasoning_request_config(spec))
    if json_schema is not None:
        payload["text"] = {
            "format": {
                "type": "json_schema",
                "name": "japanese_rp_bench_evaluation",
                "schema": dict(json_schema),
                "strict": True,
            }
        }
    elif json_mode:
        payload["text"] = {"format": {"type": "json_object"}}
    return payload


def _parse_openai_response(
    spec: ModelSpec,
    response: Mapping[str, Any],
    *,
    billing_mode: str = "standard",
    requested_max_output_tokens: int = 0,
) -> GenerationResult:
    text_parts = []
    refusal_parts = []
    for output in response.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                text_parts.append(str(content["text"]))
            elif content.get("type") == "refusal" and content.get("refusal"):
                refusal_parts.append(str(content["refusal"]))
    text = "\n".join(text_parts or refusal_parts).strip()
    usage = response.get("usage") or {}
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    status = str(response.get("status", ""))
    incomplete_details = response.get("incomplete_details") or {}
    incomplete_reason = str(incomplete_details.get("reason", ""))
    if status == "incomplete":
        termination_category = (
            "truncated" if incomplete_reason == "max_output_tokens" else "incomplete"
        )
    elif status in {"failed", "cancelled"}:
        termination_category = "error"
    elif refusal_parts:
        termination_category = "refusal"
    elif status == "completed":
        termination_category = "completed"
    else:
        termination_category = "unknown"
    result = GenerationResult(
        text=text,
        requested_model=spec.id,
        resolved_model=str(response.get("model", spec.model)),
        provider=spec.provider,
        response_id=str(response.get("id", "")),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        reasoning_tokens=int(output_details.get("reasoning_tokens", 0)),
        cached_input_tokens=int(input_details.get("cached_tokens", 0)),
        billing_mode=billing_mode,
        finish_reason=incomplete_reason or status,
        termination_category=termination_category,
        response_status=status,
        incomplete_reason=incomplete_reason,
        reasoning_config=_reasoning_request_config(spec),
        requested_max_output_tokens=requested_max_output_tokens,
    )
    return _validate_generation_result(result, "OpenAI response did not contain output text")


def _generate_gemini(
    spec: ModelSpec,
    api_key: str,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool,
    json_schema: Mapping[str, Any] | None,
) -> GenerationResult:
    payload = _build_gemini_payload(
        spec,
        system_prompt,
        messages,
        max_output_tokens,
        json_mode,
        json_schema,
    )
    response = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{spec.model}:generateContent",
        payload,
        {"x-goog-api-key": api_key},
        attempts=1,
    )
    if response.get("error"):
        raise ProviderError(f"Gemini API error: {_safe_error(response['error'])}")
    return _parse_gemini_response(
        spec,
        response,
        requested_max_output_tokens=max_output_tokens,
    )


def _build_gemini_payload(
    spec: ModelSpec,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool,
    json_schema: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    generation_config: Dict[str, Any] = {"maxOutputTokens": max_output_tokens}
    generation_config.update(_reasoning_request_config(spec))
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
    return {
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


def _parse_gemini_response(
    spec: ModelSpec,
    response: Mapping[str, Any],
    *,
    billing_mode: str = "standard",
    requested_max_output_tokens: int = 0,
) -> GenerationResult:
    text_parts = []
    candidates = response.get("candidates", [])
    for candidate in candidates:
        for part in (candidate.get("content") or {}).get("parts", []):
            if part.get("text") and not part.get("thought", False):
                text_parts.append(str(part["text"]))
    text = "\n".join(text_parts).strip()
    finish_reasons = [str(item.get("finishReason", "")) for item in candidates]
    prompt_feedback = response.get("promptFeedback") or {}
    block_reason = str(prompt_feedback.get("blockReason", ""))
    finish_reason = next((reason for reason in finish_reasons if reason), block_reason)
    termination_category = _classify_finish_reason(finish_reason)
    usage = response.get("usageMetadata") or {}
    reasoning_tokens = int(usage.get("thoughtsTokenCount", 0))
    output_tokens = int(usage.get("candidatesTokenCount", 0)) + reasoning_tokens
    result = GenerationResult(
        text=text,
        requested_model=spec.id,
        resolved_model=str(response.get("modelVersion", spec.model)),
        provider=spec.provider,
        response_id=str(response.get("responseId", "")),
        input_tokens=int(usage.get("promptTokenCount", 0)),
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cached_input_tokens=int(usage.get("cachedContentTokenCount", 0)),
        billing_mode=billing_mode,
        finish_reason=finish_reason,
        termination_category=termination_category,
        reasoning_config=_reasoning_request_config(spec),
        requested_max_output_tokens=requested_max_output_tokens,
    )
    return _validate_generation_result(
        result,
        f"Gemini response did not contain output text: {finish_reasons or [block_reason]}",
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
    payload = _build_anthropic_payload(
        spec,
        system_prompt,
        messages,
        max_output_tokens,
        json_mode,
        json_schema,
    )
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
    return _parse_anthropic_response(
        spec,
        response,
        provider_name=provider_name,
        requested_max_output_tokens=max_output_tokens,
    )


def _build_anthropic_payload(
    spec: ModelSpec,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool,
    json_schema: Mapping[str, Any] | None,
) -> Dict[str, Any]:
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
    payload.update(_reasoning_request_config(spec))
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
    return payload


def _parse_anthropic_response(
    spec: ModelSpec,
    response: Mapping[str, Any],
    *,
    provider_name: str = "Anthropic",
    billing_mode: str = "standard",
    requested_max_output_tokens: int = 0,
) -> GenerationResult:
    text = "\n".join(
        str(block["text"])
        for block in response.get("content", [])
        if block.get("type") == "text" and block.get("text")
    ).strip()
    finish_reason = str(response.get("stop_reason", ""))
    usage = response.get("usage") or {}
    output_details = usage.get("output_tokens_details") or {}
    result = GenerationResult(
        text=text,
        requested_model=spec.id,
        resolved_model=str(response.get("model", spec.model)),
        provider=spec.provider,
        response_id=str(response.get("id", "")),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        reasoning_tokens=int(output_details.get("thinking_tokens", 0)),
        cached_input_tokens=int(usage.get("cache_read_input_tokens", 0)),
        billing_mode=billing_mode,
        finish_reason=finish_reason,
        termination_category=_classify_finish_reason(finish_reason),
        reasoning_config=_reasoning_request_config(spec),
        requested_max_output_tokens=requested_max_output_tokens,
    )
    return _validate_generation_result(
        result,
        f"Anthropic response did not contain output text: {finish_reason}",
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
    payload.update(_reasoning_request_config(spec))
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
    finish_reasons = [str(item.get("finish_reason", "")) for item in choices]
    finish_reason = next((reason for reason in finish_reasons if reason), "")
    usage = response.get("usage") or {}
    input_details = usage.get("prompt_tokens_details") or {}
    output_details = usage.get("completion_tokens_details") or {}
    result = GenerationResult(
        text=text,
        requested_model=spec.id,
        resolved_model=str(response.get("model", spec.model)),
        provider=spec.provider,
        response_id=str(response.get("id", "")),
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
        reasoning_tokens=int(output_details.get("reasoning_tokens", 0)),
        cached_input_tokens=int(input_details.get("cached_tokens", 0)),
        finish_reason=finish_reason,
        termination_category=_classify_finish_reason(finish_reason),
        reasoning_config=_reasoning_request_config(spec),
        requested_max_output_tokens=max_output_tokens,
    )
    return _validate_generation_result(
        result,
        f"OpenCode Go response did not contain output text: {finish_reasons}",
    )


def _classify_finish_reason(reason: str) -> str:
    normalized = reason.strip().lower()
    if not normalized:
        return "unknown"
    if normalized in {
        "max_tokens",
        "max_output_tokens",
        "length",
        "model_context_window_exceeded",
    }:
        return "truncated"
    if normalized in {
        "safety",
        "content_filter",
        "recitation",
        "language",
        "blocklist",
        "prohibited_content",
        "spii",
        "image_safety",
    }:
        return "safety"
    if normalized in {"refusal", "refused"}:
        return "refusal"
    if normalized in {"stop", "end_turn", "stop_sequence", "completed"}:
        return "completed"
    if normalized in {"failed", "cancelled", "error"}:
        return "error"
    return "other"


def _validate_generation_result(
    result: GenerationResult,
    empty_response_message: str,
) -> GenerationResult:
    if result.termination_category == "truncated":
        raise TruncatedGenerationError(
            f"Generation was truncated: {result.finish_reason or 'unknown reason'}",
            result,
        )
    if result.termination_category == "incomplete":
        raise IncompleteGenerationError(
            f"Generation was incomplete: {result.incomplete_reason or result.finish_reason}",
            result,
        )
    if result.termination_category == "error":
        raise FailedGenerationError(
            f"Generation failed: {result.finish_reason or result.response_status}",
            result,
        )
    if result.termination_category in {"other", "unknown"}:
        raise UnexpectedGenerationError(
            "Generation ended with an unsupported termination reason: "
            f"{result.finish_reason or 'missing'}",
            result,
        )
    if result.termination_category == "safety":
        raise BlockedGenerationError(
            "Generation was stopped by a safety filter: "
            f"{result.finish_reason or result.termination_category}",
            result,
        )
    if not result.text:
        if result.termination_category == "refusal":
            raise BlockedGenerationError(
                "Generation was blocked without response text: "
                f"{result.finish_reason or result.termination_category}",
                result,
            )
        raise ProviderError(empty_response_message)
    return result


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
