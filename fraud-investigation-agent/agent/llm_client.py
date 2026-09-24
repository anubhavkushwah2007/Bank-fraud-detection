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

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests

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
    """
    Rate-limited client managing Groq models with pacing, backoff, disk caching,
    and automatic failover to Google Gemini as a secondary provider.
    """

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

        # Gemini fallback provider
        self.gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        self.gemini_model = os.getenv("GEMINI_MODEL") or os.getenv("GOOGLE_MODEL", "gemini-3.6-flash")

        # Disk cache directory
        self.cache_dir = Path(__file__).resolve().parent.parent / "data" / "llm_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._client: Optional[Groq] = None
        if _GROQ_AVAILABLE and self.api_key:
            try:
                self._client = Groq(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize Groq client: {e}")

        self._last_call_time: Dict[str, float] = {}
        self._calls_count: Dict[str, int] = {
            self.primary_model: 0,
            self.fallback_model: 0,
            self.gemini_model: 0,
        }
        self._tokens_count: Dict[str, int] = {
            self.primary_model: 0,
            self.fallback_model: 0,
            self.gemini_model: 0,
        }
        self._active_model = self.primary_model
        self._case_tokens = 0

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

    def reset_case_tokens(self) -> None:
        """Reset token consumption counter for the current case."""
        self._case_tokens = 0

    def get_case_tokens(self) -> int:
        """Return total tokens consumed during the current case."""
        return self._case_tokens

    def _get_cache(self, key: str) -> Optional[Dict[str, Any]]:
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _set_cache(self, key: str, data: Dict[str, Any]) -> None:
        cache_file = self.cache_dir / f"{key}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to write LLM cache: {e}")

    def _invoke_gemini(
        self,
        norm_messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> Tuple[str, int]:
        """Invoke Gemini fallback provider via standard REST API."""
        if not self.gemini_api_key:
            raise RuntimeError("Gemini fallback invoked but no GEMINI_API_KEY / GOOGLE_API_KEY configured")

        contents = []
        for m in norm_messages:
            role = "user" if m.get("role") in ("user", "system") else "model"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_api_key}"
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            }
        }
        resp = requests.post(url, json=payload, timeout=35)
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API returned status {resp.status_code}: {resp.text}")

        res_data = resp.json()
        candidates = res_data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"No candidates returned from Gemini: {res_data}")

        content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        tokens = res_data.get("usageMetadata", {}).get("totalTokenCount", 0)
        return content.strip(), int(tokens)

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
        Execute an LLM chat completion with disk caching, rate-limiting, exponential backoff,
        and automatic failover to Gemini.
        """
        norm_messages = self._normalize_messages(messages)
        target_model = model_override or self._active_model

        # 1. Check disk cache
        cache_raw = json.dumps({
            "messages": norm_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "json_mode": json_mode,
        }, sort_keys=True)
        cache_key = hashlib.sha256(cache_raw.encode("utf-8")).hexdigest()

        cached = self._get_cache(cache_key)
        if cached is not None:
            content = str(cached.get("content", ""))
            tokens = int(cached.get("tokens", 0))
            model_used = cached.get("model", target_model)
            self._case_tokens += tokens
            self._tokens_count[model_used] = self._tokens_count.get(model_used, 0) + tokens
            return content

        # 2. Try Groq models first
        models_to_try = [target_model]
        if target_model == self.primary_model and self.fallback_model != self.primary_model:
            models_to_try.append(self.fallback_model)

        last_error = None
        for current_model in models_to_try:
            if not self._client:
                break
            if self._calls_count.get(current_model, 0) >= self.daily_quota:
                logger.warning(f"Daily quota reached for model {current_model} ({self.daily_quota}). Failing over.")
                continue

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
                    self._case_tokens += tokens
                    self._active_model = current_model

                    self._set_cache(cache_key, {"content": content.strip(), "tokens": tokens, "model": current_model})
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
                        break

            logger.warning(f"Exhausted retries for {current_model}. Switching model if available.")

        # 3. Fallback to Gemini if Groq fails or hits rate limits
        if self.gemini_api_key:
            logger.info(f"Failing over to Gemini provider ({self.gemini_model})")
            try:
                content, tokens = self._invoke_gemini(norm_messages, max_tokens, temperature)
                self._record_call(self.gemini_model, tokens)
                self._case_tokens += tokens
                self._active_model = self.gemini_model
                self._set_cache(cache_key, {"content": content, "tokens": tokens, "model": self.gemini_model})
                return content
            except Exception as ge:
                logger.error(f"Gemini fallback failed: {ge}")
                last_error = ge

        raise RuntimeError(f"All LLM attempts failed (Groq + Gemini). Last error: {last_error}")



# ─── Global Singleton ─────────────────────────────────────────────────────────

_llm_instance: Optional[RateLimitedLLM] = None


def get_rate_limited_llm() -> RateLimitedLLM:
    """Retrieve or initialize the global singleton RateLimitedLLM instance."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = RateLimitedLLM()
    return _llm_instance
