"""
agent/llm_client.py
───────────────────
Centralized, rate-limited LLM client for Groq models with:
- Token-bucket pacing (enforces <=25 RPM, safe under Groq's 30 RPM limit)
- Exponential backoff with retry (2s, 4s, 8s) on HTTP 429 / rate limits
- Automatic model failover from primary (openai/gpt-oss-120b) to fallback (qwen/qwen3.8-27b)
- Call count and token usage tracking with quota logging
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
    else:
        load_dotenv()
except ImportError:
    pass

try:
    from groq import Groq, RateLimitError, APIError
    _GROQ_AVAILABLE = True
except ImportError:
    _GROQ_AVAILABLE = False
    Groq = None
    RateLimitError = Exception
    APIError = Exception

logger = logging.getLogger(__name__)


class RateLimitedLLM:
    """Rate-limited client managing Groq model calls with pacing, backoff, and failover."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        primary_model: str = "openai/gpt-oss-120b",
        fallback_model: str = "qwen/qwen3.8-27b",
        max_rpm: int = 25,
        daily_quota: int = 1000,
    ):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.primary_model = primary_model or os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
        self.fallback_model = fallback_model or os.getenv("GROQ_FALLBACK_MODEL", "qwen/qwen3.8-27b")
        self.max_rpm = max_rpm
        self.min_interval = 60.0 / max(1, max_rpm)  # ~2.4s interval for 25 RPM
        self.daily_quota = daily_quota

        self._client: Optional[Groq] = None
        if _GROQ_AVAILABLE and self.api_key:
            try:
                self._client = Groq(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize Groq client: {e}")

        self._last_call_time: Dict[str, float] = {}
        self._calls_count: Dict[str, int] = {self.primary_model: 0, self.fallback_model: 0}
        self._tokens_count: Dict[str, int] = {self.primary_model: 0, self.fallback_model: 0}
        self._active_model = self.primary_model

    @property
    def active_model(self) -> str:
        return self._active_model

    @property
    def calls_count(self) -> Dict[str, int]:
        return dict(self._calls_count)

    @property
    def tokens_count(self) -> Dict[str, int]:
        return dict(self._tokens_count)

    @property
    def calls_remaining(self) -> Dict[str, int]:
        return {
            m: max(0, self.daily_quota - self._calls_count.get(m, 0))
            for m in [self.primary_model, self.fallback_model]
        }

    def _pace(self, model: str) -> None:
        """Enforce rate-limiting interval between calls for the given model."""
        last_time = self._last_call_time.get(model, 0.0)
        elapsed = time.time() - last_time
        if elapsed < self.min_interval:
            sleep_duration = self.min_interval - elapsed
            logger.debug(f"[LLM Pacer] Sleeping {sleep_duration:.2f}s for model {model} (RPM limit {self.max_rpm})")
            time.sleep(sleep_duration)

    def _record_call(self, model: str, completion_tokens: int = 0) -> None:
        """Update timestamps and call counters."""
        self._last_call_time[model] = time.time()
        self._calls_count[model] = self._calls_count.get(model, 0) + 1
        self._tokens_count[model] = self._tokens_count.get(model, 0) + completion_tokens

    def _normalize_messages(self, messages: Union[str, List[Any]]) -> List[Dict[str, str]]:
        """Normalize messages from string, list of dicts, or LangChain BaseMessage objects."""
        if isinstance(messages, str):
            return [{"role": "user", "content": messages}]

        normalized = []
        for msg in messages:
            if isinstance(msg, dict):
                normalized.append(msg)
            elif hasattr(msg, "content"):
                # Handle LangChain message objects (HumanMessage, SystemMessage, AIMessage)
                role = "user"
                msg_type = getattr(msg, "type", "").lower()
                if "system" in msg_type:
                    role = "system"
                elif "ai" in msg_type or "assistant" in msg_type:
                    role = "assistant"
                normalized.append({"role": role, "content": str(msg.content)})
            else:
                normalized.append({"role": "user", "content": str(msg)})
        return normalized

    def invoke(
        self,
        messages: Union[str, List[Any]],
        max_tokens: int = 1000,
        temperature: float = 0.1,
        json_mode: bool = False,
        model_override: Optional[str] = None,
    ) -> str:
        """
        Execute an LLM chat completion with rate-limiting, exponential backoff,
        and automatic model failover.
        """
        if not self._client:
            raise RuntimeError("Groq client not initialized (missing API key or groq package)")

        norm_messages = self._normalize_messages(messages)
        target_model = model_override or self._active_model
        models_to_try = [target_model]
        if target_model == self.primary_model and self.fallback_model != self.primary_model:
            models_to_try.append(self.fallback_model)

        last_error = None
        for current_model in models_to_try:
            # Check remaining quota
            if self._calls_count.get(current_model, 0) >= self.daily_quota:
                logger.warning(f"Daily quota reached for model {current_model} ({self.daily_quota}). Failing over.")
                continue

            # Up to 3 retries with exponential backoff on 429
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    self._pace(current_model)
                    kwargs: Dict[str, Any] = {
                        "model": current_model,
                        "messages": norm_messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    }
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}

                    response = self._client.chat.completions.create(**kwargs)
                    content = response.choices[0].message.content or ""
                    tokens = getattr(response.usage, "total_tokens", 0) if response.usage else 0
                    self._record_call(current_model, tokens)

                    # Update active model on success
                    self._active_model = current_model
                    return content.strip()

                except RateLimitError as rle:
                    last_error = rle
                    wait_s = min(60, (2 ** attempt))
                    logger.warning(
                        f"Rate limit hit (429) for {current_model} (attempt {attempt}/{max_attempts}). "
                        f"Waiting {wait_s}s. Details: {rle}"
                    )
                    time.sleep(wait_s)

                except Exception as e:
                    last_error = e
                    err_msg = str(e).lower()
                    if "429" in err_msg or "rate limit" in err_msg:
                        wait_s = min(60, (2 ** attempt))
                        logger.warning(
                            f"Rate limit hit for {current_model} (attempt {attempt}/{max_attempts}). "
                            f"Waiting {wait_s}s. Details: {e}"
                        )
                        time.sleep(wait_s)
                    else:
                        logger.error(f"Error calling {current_model} on attempt {attempt}: {e}")
                        break  # Non-retryable error, try failover model

            logger.warning(f"Exhausted retries for {current_model}. Switching model if available.")

        raise RuntimeError(f"All LLM attempts failed across models {models_to_try}. Last error: {last_error}")


# ─── Global Singleton ─────────────────────────────────────────────────────────

_llm_instance: Optional[RateLimitedLLM] = None


def get_rate_limited_llm() -> RateLimitedLLM:
    """Retrieve or initialize the global singleton RateLimitedLLM instance."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = RateLimitedLLM()
    return _llm_instance
