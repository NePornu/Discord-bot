import os
import httpx
import logging
from typing import Optional, List

logger = logging.getLogger("AIClient")

class AIClient:
    @staticmethod
    async def analyze_logs(service_name: str, logs: str) -> Optional[str]:
        """
        Analyze service logs and return a brief diagnosis.
        """
        provider = os.getenv("AI_PROVIDER", "auto").lower()
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")
        
        if provider == "auto":
            if anthropic_key: provider = "anthropic"
            elif openai_key: provider = "openai"
            else: return None

        prompt = (
            f"Jsi expert na Linux a Docker. Analyzuj tyto logy služby '{service_name}' "
            "a stručně (jedna věta, čeština) napiš, v čem je problém a jak ho opravit.\n\n"
            f"Logy:\n{logs}"
        )

        try:
            if provider == "anthropic" and anthropic_key:
                return await AIClient._call_anthropic(prompt, anthropic_key)
            elif provider == "openai" and openai_key:
                return await AIClient._call_openai(prompt, openai_key)
        except Exception as e:
            logger.error(f"AI diagnostic failed: {e}")
            return None
        
        return None

    @staticmethod
    async def _call_anthropic(prompt: str, api_key: str) -> Optional[str]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 150,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            response.raise_for_status()
            return response.json()["content"][0]["text"].strip()

    @staticmethod
    async def _call_openai(prompt: str, api_key: str) -> Optional[str]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 150
                }
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
