"""Generic LLM service for LeadForge - OpenRouter integration."""

import httpx
import json
import logging
from typing import Optional
from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Base exception for LLM client errors."""
    pass


class LLMClient:
    """Client for OpenRouter API (supports DeepSeek, Claude, etc.)."""

    def __init__(self, api_key: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.openrouter_api_key
        self.base_url = settings.openrouter_base_url
        self.default_model = settings.deepseek_model
        self.timeout = 60

        if not self.api_key:
            raise LLMClientError(
                "OpenRouter API key not configured. "
                "Set OPENROUTER_API_KEY in .env or pass api_key explicitly."
            )

    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> dict:
        """Send a chat completion request to OpenRouter.

        Args:
            messages: List of {'role': 'user'|'assistant'|'system', 'content': str}
            model: Model name (defaults to deepseek-chat)
            temperature: 0.0-1.0
            max_tokens: Max tokens in response

        Returns:
            dict with keys: content, model, usage (prompt_tokens, completion_tokens), cost_estimate
        """
        model = model or self.default_model

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://leadforge.app",
            "X-Title": "LeadForge",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                choice = data["choices"][0]
                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)

                # Rough cost estimate (DeepSeek V4: ~$0.14/M input, ~$0.42/M output)
                input_cost = (prompt_tokens / 1_000_000) * 0.14
                output_cost = (completion_tokens / 1_000_000) * 0.42

                return {
                    "content": choice["message"]["content"],
                    "model": data.get("model", model),
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                    "cost_estimate": round(input_cost + output_cost, 6),
                    "finish_reason": choice.get("finish_reason"),
                }

            except httpx.HTTPStatusError as e:
                logger.error(f"LLM API error {e.response.status_code}: {e.response.text}")
                if e.response.status_code == 401:
                    raise LLMClientError("Invalid OpenRouter API key")
                elif e.response.status_code == 429:
                    raise LLMClientError("Rate limited by LLM provider. Retry later.")
                raise LLMClientError(f"LLM API error: {e.response.status_code}")
            except httpx.TimeoutException:
                raise LLMClientError("LLM request timed out")
            except httpx.RequestError as e:
                raise LLMClientError(f"LLM request failed: {str(e)}")

    async def chat_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> str:
        """Simple two-message chat with system prompt."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        result = await self.chat(messages, model=model, temperature=temperature)
        return result["content"]

    async def extract_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
    ) -> dict:
        """Request structured JSON output from LLM."""
        full_system = f"{system_prompt}\n\nRespond ONLY with valid JSON. No markdown, no explanation."
        result = await self.chat_structured(
            full_system, user_prompt, model=model, temperature=0.1
        )
        # Clean potential markdown fences
        text = result.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            text = text.rsplit("```", 1)[0]
        if text.startswith("```json"):
            text = text[7:]
            text = text.rsplit("```", 1)[0]
        return json.loads(text.strip())
