"""LLM client abstraction — OpenAI implementation with Mock fallback.

Supports:
  - OpenAI API (gpt-4o-mini, gpt-4o, etc.)
  - Structured output via Pydantic response_model
  - Retry with exponential backoff
  - Timeout configuration
  - Token & cost tracking
  - Graceful fallback to Mock when no API key
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Optional

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from app.config.settings import settings
from app.infrastructure.trace import trace_collector


# ── Retry Configuration ──

_RETRY_MAX = 3
_RETRY_BASE_DELAY = 1.0  # seconds
_RETRY_MAX_DELAY = 15.0
_TIMEOUT = 30.0  # default timeout seconds


# ── Response ──

@dataclass
class LLMResponse:
    content: str
    parsed: Optional[BaseModel] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = "mock"
    duration_ms: int = 0


# ── Cost tracking ──

_MODEL_COST_PER_1K = {
    "gpt-4o": {"prompt": 0.0025, "completion": 0.01},
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
    "gpt-4o-2024-08-06": {"prompt": 0.0025, "completion": 0.01},
    "gpt-4o-mini-2024-07-18": {"prompt": 0.00015, "completion": 0.0006},
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = _MODEL_COST_PER_1K.get(model, {"prompt": 0.001, "completion": 0.002})
    return (prompt_tokens * rates["prompt"] + completion_tokens * rates["completion"]) / 1000


# ── Structured Output Helpers ──

def _build_json_schema(model_class: type[BaseModel]) -> dict:
    """Build a JSON Schema for OpenAI Structured Outputs."""
    schema = model_class.model_json_schema()
    # Remove top-level $defs if present — OpenAI doesn't need them inline
    schema.pop("$defs", None)
    return schema



def _describe_schema(model_class: type[BaseModel]) -> str:
    """Build full JSON Schema dump for prompt injection (supports nested structures)."""
    import json
    return json.dumps(model_class.model_json_schema(), indent=2, ensure_ascii=False)

def _parse_response(
    content: str,
    response_model: type[BaseModel] | None,
    attempt_repair: bool = False,
) -> tuple[str, BaseModel | None]:
    """Parse JSON response into Pydantic model with repair retry.

    When initial parsing fails and attempt_repair is False, returns (content, None)
    so the caller can trigger LLM-assisted repair via _call_openai.
    """
    if response_model is None:
        return content, None

    # Try direct JSON parse
    last_error = None
    data: dict | None = None
    try:
        # Strip markdown code fences if present
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0]
        if cleaned.startswith("```json"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0]

        data = json.loads(cleaned)
        # Check for parse_failed sentinel (DeepSeek may return this)
        if isinstance(data, dict) and data.get("parse_failed"):
            return content, None  # LLM admitted failure
        parsed = response_model.model_validate(data)
        return content, parsed
    except (json.JSONDecodeError, ValidationError) as exc:
        last_error = exc
        # Fallback: try to find JSON in the response
        import re
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                if isinstance(data, dict) and data.get("parse_failed"):
                    return content, None
                parsed = response_model.model_validate(data)
                return content, parsed
            except (json.JSONDecodeError, ValidationError) as exc2:
                last_error = exc2
        # Fallback: fill missing required fields with schema defaults
        # (DeepSeek and other free-form JSON models often omit optional-looking
        #  fields that the schema marks required)
        if isinstance(data, dict):
            try:
                filled = _fill_missing_with_defaults(response_model, data)
                if filled != data:
                    parsed = response_model.model_validate(filled)
                    return content, parsed
            except (json.JSONDecodeError, ValidationError):
                pass
        # If all parsing fails, return raw content with error info
        return content, None


def _fill_missing_with_defaults(
    model_class: type[BaseModel],
    data: dict,
) -> dict:
    """Fill missing top-level fields from JSON Schema defaults."""
    schema = model_class.model_json_schema()
    props = schema.get("properties", {})
    filled = dict(data)
    for name, prop in props.items():
        if name not in filled and "default" in prop:
            filled[name] = prop["default"]
    return filled


# ── Main Client ──
def _is_deepseek(model: str, base_url: str = "") -> bool:
    """Detect if the model is DeepSeek (does not support json_schema)."""
    return "deepseek" in model.lower() or "deepseek" in (base_url or "").lower()


class LLMClient:
    """LLM client with real OpenAI support and Mock fallback.

    Usage:
        client = LLMClient()
        resp = await client.generate(
            system_prompt="You are an analyst.",
            user_prompt="Analyze...",
            response_model=ResearchPlan,     # optional Pydantic model
        )
        print(resp.parsed)  # ResearchPlan instance or None
    """

    def __init__(self) -> None:
        self.provider = settings.llm_provider
        self.model = settings.effective_model
        self.api_key = settings.effective_api_key
        self._openai_client: AsyncOpenAI | None = None
        self._base_url = settings.openai_base_url

    # ── Public API ──

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel] | None = None,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Generate a response.

        Uses OpenAI when LLM_PROVIDER=openai and API key is set.
        Falls back to Mock otherwise.
        """
        start = datetime.now()

        # --- Trace: LLM call start ---
        input_snip = user_prompt[:200].replace("\n", " ")
        trace = trace_collector.start_trace(
            task_id="",  # caller should set via metadata
            stage="llm_client",
            agent_name="",
            input_summary=f"model={self.model}, prompt={input_snip}",
            metadata={"provider": self.provider.value, "model": self.model},
        )
        # ---

        if self._use_openai():
            result = await self._generate_openai(
                system_prompt, user_prompt, response_model, temperature,
                timeout,
            )
        else:
            result = self._generate_mock(system_prompt, user_prompt, response_model)

        elapsed = int((datetime.now() - start).total_seconds() * 1000)
        result.duration_ms = elapsed

        # --- Trace: LLM call end ---
        trace_collector.end_trace(
            trace,
            success=not result.content.startswith("["),
            output_summary=f"tokens: {result.prompt_tokens}+{result.completion_tokens}, model: {result.model}",
            metadata={
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "duration_ms": elapsed,
                "model": result.model,
            },
        )
        # ---

        return result

    async def stream(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncIterator[str]:
        """Stream tokens from the LLM.

        Uses OpenAI when configured, Mock fallback otherwise.
        """
        if self._use_openai():
            async for chunk in self._stream_openai(system_prompt, user_prompt):
                yield chunk
        else:
            yield (
                f"[MOCK STREAM] Simulated streaming response for: "
                f"{user_prompt[:40]}..."
            )

    # ── Provider Detection ──

    def _use_openai(self) -> bool:
        return (
            self.api_key != "" and self.provider.value != "mock"
        )

    def _client(self) -> AsyncOpenAI:
        if self._openai_client is None:
            kwargs: dict[str, Any] = {"api_key": self.api_key}
            base_url = settings.openai_base_url
            if base_url:
                kwargs["base_url"] = base_url
            self._openai_client = AsyncOpenAI(**kwargs)
        return self._openai_client
    # ── OpenAI Implementation ──

    async def _generate_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel] | None = None,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> LLMResponse:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "timeout": timeout if timeout is not None else _TIMEOUT,
        }

        # Structured Outputs support (gpt-4o-mini+)
        if response_model is not None and not _is_deepseek(self.model, self._base_url):
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "schema": _build_json_schema(response_model),
                    "strict": True,
                },
            }

        last_error: Exception | None = None
        for attempt in range(_RETRY_MAX):
            try:
                response = await self._client().chat.completions.create(**kwargs)
            except RateLimitError as exc:
                last_error = exc
                wait = min(
                    _RETRY_BASE_DELAY * (2 ** attempt),
                    _RETRY_MAX_DELAY,
                )
                await asyncio.sleep(wait)
                continue
            except APITimeoutError as exc:
                last_error = exc
                if attempt < _RETRY_MAX - 1:
                    wait = _RETRY_BASE_DELAY * (2 ** attempt)
                    await asyncio.sleep(wait)
                    continue
                return LLMResponse(
                    content=f"[TIMEOUT] Request timed out after {kwargs['timeout']}s",
                    model=f"openai/{self.model}",
                    duration_ms=0,
                )
            except APIError as exc:
                # Fallback: json_schema → json_object for providers that
                # don't support strict structured output (e.g., DeepSeek)
                err_msg = str(exc)
                if ("response_format" in err_msg and
                        response_model is not None and
                        kwargs.get("response_format", {}).get("type") == "json_schema"):
                    kwargs["response_format"] = {"type": "json_object"}
                    # Inject schema into prompt for json_object mode
                    schema_fields = _describe_schema(response_model)
                    kwargs["messages"][-1]["content"] += (
                        "\n\n【输出格式要求】请严格输出以下JSON结构，不要添加或缺少字段：\n" +
                        schema_fields
                    )
                    continue

                last_error = exc
                if attempt < _RETRY_MAX - 1:
                    wait = _RETRY_BASE_DELAY * (2 ** attempt)
                    await asyncio.sleep(wait)
                    continue
                return LLMResponse(
                    content=f"[API_ERROR] {exc}",
                    model=f"openai/{self.model}",
                    duration_ms=0,
                )

            # Process successful response
            choice = response.choices[0]
            raw_content = choice.message.content or ""
            prompt_tokens = response.usage.prompt_tokens if response.usage else 0
            completion_tokens = response.usage.completion_tokens if response.usage else 0

            # Parse structured output
            content, parsed = _parse_response(raw_content, response_model)

            return LLMResponse(
                content=content,
                parsed=parsed,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=f"openai/{response.model}",
                duration_ms=0,
            )

        # All retries exhausted
        return LLMResponse(
            content=f"[RETRY_EXHAUSTED] {last_error}",
            model=f"openai/{self.model}",
            prompt_tokens=0,
            completion_tokens=0,
            duration_ms=0,
        )

    async def _stream_openai(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncIterator[str]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            stream = await self._client().chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                stream=True,
                timeout=timeout if timeout is not None else _TIMEOUT,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
        except Exception:
            yield "[STREAM_ERROR] Streaming failed, falling back to mock..."
            yield (
                f"[MOCK STREAM] Simulated response for: {user_prompt[:40]}..."
            )

    # ── Mock Fallback ──

    @staticmethod
    def _generate_mock(
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel] | None = None,
    ) -> LLMResponse:
        """Return mock response when OpenAI is not configured."""
        content = (
            f"[MOCK] Received: {user_prompt[:60]}..."
        )

        parsed: Optional[BaseModel] = None
        if response_model:
            try:
                parsed = response_model()
            except ValidationError:
                parsed = None

        return LLMResponse(
            content=content,
            parsed=parsed,
            prompt_tokens=128,
            completion_tokens=64,
            model="mock",
            duration_ms=0,
        )


# ── Singleton ──

llm_client = LLMClient()
