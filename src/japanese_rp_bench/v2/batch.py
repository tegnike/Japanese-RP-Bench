"""Resumable provider Batch API adapters for asynchronous generation calls."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence

from japanese_rp_bench.v2.providers import (
    GenerationOutcomeError,
    GenerationResult,
    ModelSpec,
    ProviderError,
    RateLimitError,
    _build_anthropic_payload,
    _build_gemini_payload,
    _build_openai_payload,
    _parse_anthropic_response,
    _parse_gemini_response,
    _parse_openai_response,
    _post_json,
    _safe_error,
    _safe_error_body,
)


GEMINI_TERMINAL_STATES = {
    "JOB_STATE_SUCCEEDED",
    "JOB_STATE_FAILED",
    "JOB_STATE_CANCELLED",
    "JOB_STATE_EXPIRED",
    "BATCH_STATE_SUCCEEDED",
    "BATCH_STATE_FAILED",
    "BATCH_STATE_CANCELLED",
    "BATCH_STATE_EXPIRED",
}
OPENAI_TERMINAL_STATES = {"completed", "failed", "expired", "cancelled"}


@dataclass(frozen=True)
class BatchRequest:
    custom_id: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class BatchItemResult:
    custom_id: str
    generation: GenerationResult | None
    error: str | None = None
    terminal: bool = False


def build_batch_request(
    spec: ModelSpec,
    custom_id: str,
    system_prompt: str,
    messages: Sequence[Mapping[str, str]],
    max_output_tokens: int,
    json_mode: bool = False,
    json_schema: Mapping[str, Any] | None = None,
) -> BatchRequest:
    if spec.provider == "openai":
        payload = _build_openai_payload(
            spec,
            system_prompt,
            messages,
            max_output_tokens,
            json_mode,
            json_schema,
        )
    elif spec.provider == "gemini":
        payload = _build_gemini_payload(
            spec,
            system_prompt,
            messages,
            max_output_tokens,
            json_mode,
            json_schema,
        )
    elif spec.provider == "anthropic":
        payload = _build_anthropic_payload(
            spec,
            system_prompt,
            messages,
            max_output_tokens,
            json_mode,
            json_schema,
        )
    else:
        raise ProviderError(f"Provider does not support batch execution: {spec.provider}")
    return BatchRequest(custom_id=custom_id, payload=payload)


def submit_batch(
    spec: ModelSpec,
    requests: Sequence[BatchRequest],
    display_name: str,
) -> Dict[str, Any]:
    if not requests:
        raise ValueError("Cannot submit an empty batch")
    api_key = _api_key(spec)
    if spec.provider == "openai":
        if len(requests) > 50_000:
            raise ProviderError("OpenAI batch exceeds the 50,000 request limit")
        rows: List[Dict[str, Any]] = [
            {
                "custom_id": item.custom_id,
                "method": "POST",
                "url": "/v1/responses",
                "body": dict(item.payload),
            }
            for item in requests
        ]
        models = {str(row["body"].get("model", "")) for row in rows}
        if models != {spec.model}:
            raise ProviderError("OpenAI batch input must contain exactly one configured model")
        input_bytes = "".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in rows
        ).encode("utf-8")
        if len(input_bytes) >= 200_000_000:
            raise ProviderError("OpenAI batch input exceeds the 200 MB file limit")
        uploaded = _post_multipart_file(
            "https://api.openai.com/v1/files",
            input_bytes,
            filename=f"{display_name}.jsonl",
            fields={"purpose": "batch"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        input_file_id = str(uploaded.get("id", ""))
        if uploaded.get("error") or not input_file_id:
            raise ProviderError(
                f"OpenAI batch input upload failed: {_safe_error(uploaded.get('error', uploaded))}"
            )
        response = _post_json(
            "https://api.openai.com/v1/batches",
            {
                "input_file_id": input_file_id,
                "endpoint": "/v1/responses",
                "completion_window": "24h",
                "metadata": {"description": display_name},
            },
            {"Authorization": f"Bearer {api_key}"},
            attempts=1,
        )
        batch_id = str(response.get("id", ""))
        response = {**response, "input_file": uploaded}
    elif spec.provider == "gemini":
        payload = {
            "batch": {
                "display_name": display_name,
                "input_config": {
                    "requests": {
                        "requests": [
                            {
                                "request": dict(item.payload),
                                "metadata": {"key": item.custom_id},
                            }
                            for item in requests
                        ]
                    }
                },
            }
        }
        encoded_size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if encoded_size >= 20_000_000:
            raise ProviderError(
                "Gemini inline batch exceeds the 20 MB limit; split the benchmark batch"
            )
        response = _post_json(
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/{spec.model}:batchGenerateContent",
            payload,
            {"x-goog-api-key": api_key},
            attempts=1,
        )
        batch_id = str(response.get("name", ""))
    elif spec.provider == "anthropic":
        response = _post_json(
            "https://api.anthropic.com/v1/messages/batches",
            {
                "requests": [
                    {"custom_id": item.custom_id, "params": dict(item.payload)}
                    for item in requests
                ]
            },
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            attempts=1,
        )
        batch_id = str(response.get("id", ""))
    else:
        raise ProviderError(f"Provider does not support batch execution: {spec.provider}")
    if response.get("error") or not batch_id:
        raise ProviderError(f"Batch creation failed: {_safe_error(response.get('error', response))}")
    return {"batch_id": batch_id, "provider_response": response}


def wait_for_batch(
    spec: ModelSpec,
    batch_id: str,
    poll_interval_seconds: float,
) -> Dict[str, Any]:
    while True:
        status = retrieve_batch(spec, batch_id)
        if batch_is_terminal(spec, status):
            return status
        time.sleep(max(1.0, poll_interval_seconds))


def retrieve_batch(spec: ModelSpec, batch_id: str) -> Dict[str, Any]:
    api_key = _api_key(spec)
    if spec.provider == "openai":
        url = f"https://api.openai.com/v1/batches/{batch_id}"
        headers = {"Authorization": f"Bearer {api_key}"}
    elif spec.provider == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/{batch_id}"
        headers = {"x-goog-api-key": api_key}
    elif spec.provider == "anthropic":
        url = f"https://api.anthropic.com/v1/messages/batches/{batch_id}"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    else:
        raise ProviderError(f"Provider does not support batch execution: {spec.provider}")
    return _get_json(url, headers)


def batch_state(spec: ModelSpec, status: Mapping[str, Any]) -> str:
    if spec.provider == "openai":
        return str(status.get("status", "unknown"))
    if spec.provider == "gemini":
        metadata = status.get("metadata") or {}
        return str(status.get("state") or metadata.get("state") or "UNKNOWN")
    return str(status.get("processing_status", "unknown"))


def batch_is_terminal(spec: ModelSpec, status: Mapping[str, Any]) -> bool:
    if spec.provider == "openai":
        return batch_state(spec, status) in OPENAI_TERMINAL_STATES
    if spec.provider == "gemini":
        return batch_state(spec, status) in GEMINI_TERMINAL_STATES
    return batch_state(spec, status) == "ended"


def read_batch_results(
    spec: ModelSpec,
    batch_id: str,
    status: Mapping[str, Any],
    requests: Sequence[BatchRequest],
) -> List[BatchItemResult]:
    if spec.provider == "openai":
        rows: List[Dict[str, Any]] = []
        for file_id_key in ("output_file_id", "error_file_id"):
            file_id = status.get(file_id_key)
            if file_id:
                rows.extend(
                    _get_jsonl(
                        f"https://api.openai.com/v1/files/{file_id}/content",
                        {"Authorization": f"Bearer {_api_key(spec)}"},
                    )
                )
        row_by_id = {str(row.get("custom_id", "")): row for row in rows}
        openai_results: List[BatchItemResult] = []
        for request in requests:
            row = row_by_id.get(request.custom_id)
            if row is None:
                openai_results.append(
                    BatchItemResult(
                        request.custom_id,
                        None,
                        f"OpenAI batch result missing in state {batch_state(spec, status)}",
                    )
                )
                continue
            response = row.get("response") or {}
            body = response.get("body") if isinstance(response, Mapping) else None
            status_code = int(response.get("status_code", 0)) if isinstance(response, Mapping) else 0
            if 200 <= status_code < 300 and isinstance(body, Mapping):
                try:
                    generation = _parse_openai_response(
                        spec,
                        body,
                        billing_mode="batch",
                        requested_max_output_tokens=int(
                            request.payload.get("max_output_tokens", 0)
                        ),
                    )
                except GenerationOutcomeError as exc:
                    openai_results.append(
                        BatchItemResult(request.custom_id, exc.result, str(exc), terminal=True)
                    )
                except ProviderError as exc:
                    openai_results.append(BatchItemResult(request.custom_id, None, str(exc)))
                else:
                    openai_results.append(BatchItemResult(request.custom_id, generation))
            else:
                openai_results.append(
                    BatchItemResult(
                        request.custom_id,
                        None,
                        _safe_error(row.get("error") or body or response or row),
                    )
                )
        return openai_results

    if spec.provider == "gemini":
        request_by_id = {request.custom_id: request for request in requests}
        state = batch_state(spec, status)
        if state not in {"JOB_STATE_SUCCEEDED", "BATCH_STATE_SUCCEEDED"}:
            error = _safe_error(status.get("error", state))
            return [BatchItemResult(item.custom_id, None, error) for item in requests]
        response_root = status.get("response") or status
        destination = status.get("dest") or {}
        inline = response_root.get("inlinedResponses") or destination.get("inlinedResponses")
        if isinstance(inline, Mapping):
            inline = inline.get("inlinedResponses")
        if not isinstance(inline, list):
            raise ProviderError("Gemini batch did not contain inline responses")
        gemini_results: List[BatchItemResult] = []
        for index, item in enumerate(inline):
            metadata = item.get("metadata") or {}
            custom_id = str(
                metadata.get("key")
                or (requests[index].custom_id if index < len(requests) else "")
            )
            response = item.get("response")
            if not custom_id:
                raise ProviderError("Gemini batch response is missing its request key")
            if isinstance(response, Mapping):
                try:
                    generation = _parse_gemini_response(
                        spec,
                        response,
                        billing_mode="batch",
                        requested_max_output_tokens=int(
                            (
                                request_by_id.get(custom_id, BatchRequest("", {})).payload.get(
                                    "generationConfig", {}
                                )
                            ).get("maxOutputTokens", 0)
                        ),
                    )
                except GenerationOutcomeError as exc:
                    gemini_results.append(
                        BatchItemResult(custom_id, exc.result, str(exc), terminal=True)
                    )
                except ProviderError as exc:
                    gemini_results.append(BatchItemResult(custom_id, None, str(exc)))
                else:
                    gemini_results.append(BatchItemResult(custom_id, generation))
            else:
                gemini_results.append(
                    BatchItemResult(custom_id, None, _safe_error(item.get("error", item)))
                )
        return gemini_results

    if spec.provider == "anthropic":
        request_by_id = {request.custom_id: request for request in requests}
        rows = _get_jsonl(
            f"https://api.anthropic.com/v1/messages/batches/{batch_id}/results",
            {
                "x-api-key": _api_key(spec),
                "anthropic-version": "2023-06-01",
            },
        )
        anthropic_results: List[BatchItemResult] = []
        for row in rows:
            custom_id = str(row.get("custom_id", ""))
            result = row.get("result") or {}
            if result.get("type") == "succeeded" and isinstance(result.get("message"), Mapping):
                try:
                    generation = _parse_anthropic_response(
                        spec,
                        result["message"],
                        billing_mode="batch",
                        requested_max_output_tokens=int(
                            request_by_id.get(custom_id, BatchRequest("", {})).payload.get(
                                "max_tokens", 0
                            )
                        ),
                    )
                except GenerationOutcomeError as exc:
                    anthropic_results.append(
                        BatchItemResult(custom_id, exc.result, str(exc), terminal=True)
                    )
                except ProviderError as exc:
                    anthropic_results.append(BatchItemResult(custom_id, None, str(exc)))
                else:
                    anthropic_results.append(BatchItemResult(custom_id, generation))
            else:
                anthropic_results.append(
                    BatchItemResult(custom_id, None, _safe_error(result.get("error", result)))
                )
        return anthropic_results

    raise ProviderError(f"Provider does not support batch execution: {spec.provider}")


def _api_key(spec: ModelSpec) -> str:
    api_key = os.environ.get(spec.api_key_env)
    if not api_key:
        raise ProviderError(f"Required environment variable is not set: {spec.api_key_env}")
    return api_key


def _post_multipart_file(
    url: str,
    content: bytes,
    *,
    filename: str,
    fields: Mapping[str, str],
    headers: Mapping[str, str],
) -> Dict[str, Any]:
    boundary = f"japanese-rp-bench-{uuid.uuid4().hex}"
    chunks: List[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            ).encode("utf-8"),
            b"Content-Type: application/jsonl\r\n\r\n",
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    request = urllib.request.Request(
        url,
        data=b"".join(chunks),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "Japanese-RP-Bench-v2/0.1",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 429:
            raise RateLimitError(f"Provider HTTP 429: {_safe_error_body(body)}") from exc
        raise ProviderError(f"Provider HTTP {exc.code}: {_safe_error_body(body)}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError(f"Provider request failed: {type(exc).__name__}") from exc
    except json.JSONDecodeError as exc:
        raise ProviderError("Provider response was not valid JSON") from exc
    if not isinstance(value, dict):
        raise ProviderError("Provider response JSON root is not an object")
    return value


def _get_json(
    url: str,
    headers: Mapping[str, str],
    attempts: int = 4,
) -> Dict[str, Any]:
    body = _get_bytes(url, headers, attempts=attempts)
    try:
        value = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProviderError("Provider response was not valid JSON") from exc
    if not isinstance(value, dict):
        raise ProviderError("Provider response JSON root is not an object")
    return value


def _get_jsonl(
    url: str,
    headers: Mapping[str, str],
    attempts: int = 4,
) -> List[Dict[str, Any]]:
    body = _get_bytes(url, headers, attempts=attempts).decode("utf-8")
    rows: List[Dict[str, Any]] = []
    for line in body.splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ProviderError("Provider JSONL result line is not an object")
        rows.append(value)
    return rows


def _get_bytes(
    url: str,
    headers: Mapping[str, str],
    attempts: int,
) -> bytes:
    request_headers = {
        "User-Agent": "Japanese-RP-Bench-v2/0.1",
        **headers,
    }
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, headers=request_headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                raise RateLimitError(f"Provider HTTP 429: {_safe_error_body(body)}") from exc
            if not 500 <= exc.code < 600 or attempt == attempts:
                raise ProviderError(
                    f"Provider HTTP {exc.code}: {_safe_error_body(body)}"
                ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts:
                raise ProviderError(f"Provider request failed: {type(exc).__name__}") from exc
        time.sleep(min(2 ** (attempt - 1), 8))
    raise ProviderError("Provider request failed after retries")
