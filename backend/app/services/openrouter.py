import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings


class ModelProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompletionResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


def _headers() -> dict[str, str]:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise ModelProviderError("OPENROUTER_API_KEY is not configured")
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "X-Title": settings.openrouter_app_name,
    }
    if settings.openrouter_app_url:
        headers["HTTP-Referer"] = settings.openrouter_app_url
    return headers


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{settings.openrouter_base_url.rstrip('/')}/embeddings",
            headers=_headers(),
            json={"model": settings.openrouter_embedding_model, "input": texts},
        )
    if response.is_error:
        raise ModelProviderError(f"Embedding request failed ({response.status_code}): {response.text[:500]}")
    data = response.json().get("data", [])
    ordered = sorted(data, key=lambda item: item.get("index", 0))
    vectors = [item["embedding"] for item in ordered]
    if len(vectors) != len(texts):
        raise ModelProviderError("Embedding provider returned an unexpected vector count")
    for vector in vectors:
        if len(vector) != settings.embedding_dimension:
            raise ModelProviderError(
                f"Expected {settings.embedding_dimension}-dimension embedding, received {len(vector)}"
            )
    return vectors


async def grounded_completion(*, system_prompt: str, user_prompt: str) -> CompletionResult:
    settings = get_settings()
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
            headers=_headers(),
            json={
                "model": settings.openrouter_llm_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
            },
        )
    if response.is_error:
        raise ModelProviderError(f"Answer request failed ({response.status_code}): {response.text[:500]}")
    body: dict[str, Any] = response.json()
    usage = body.get("usage", {})
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelProviderError("Answer provider returned an invalid response") from exc
    return CompletionResult(
        text=text.strip(),
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        latency_ms=round((time.perf_counter() - started) * 1000),
    )

