"""LLM client wrapper for verification checks.

Uses LiteLLM for model-agnostic completion calls with built-in timeout
handling.  When the LLM is unavailable or times out, returns None so
callers can degrade gracefully.
"""

import json
import logging
import os
import re
from typing import Any, Dict, Optional

from litellm import acompletion

logger = logging.getLogger("agentguard.verification-engine.llm")

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_TIMEOUT_S = 5

# Providers that support the response_format parameter via Vercel AI Gateway.
_JSON_MODE_PREFIXES = ("openai/", "gpt-")


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from LLM response, handling markdown fences."""
    # Try direct parse first
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Try extracting from markdown code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass

    # Try finding first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

    return None


async def call_llm(
    prompt: str,
    system: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Send a prompt to the LLM and parse the JSON response.

    Args:
        prompt: The user message to send.
        system: Optional system message.

    Returns:
        Parsed JSON dict from the LLM response, or None on timeout/error.
    """
    model = os.environ.get("VERIFICATION_MODEL", DEFAULT_MODEL)
    timeout_s = float(os.environ.get("VERIFICATION_TIMEOUT_S", DEFAULT_TIMEOUT_S))

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    api_base = os.environ.get("LITELLM_API_URL") or os.environ.get("OPENAI_API_BASE")
    api_key = os.environ.get("LITELLM_API_KEY") or os.environ.get("OPENAI_API_KEY")

    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "timeout": timeout_s,
        "temperature": 0.0,
    }

    # Only include response_format for providers that support it
    model_lower = model.lower()
    if any(model_lower.startswith(p) for p in _JSON_MODE_PREFIXES):
        kwargs["response_format"] = {"type": "json_object"}

    if api_base:
        kwargs["api_base"] = api_base
    if api_key:
        kwargs["api_key"] = api_key

    try:
        response = await acompletion(**kwargs)
        content = response.choices[0].message.content
        result = _extract_json(content)
        if result is None:
            logger.warning("LLM returned non-JSON response: %s", content[:200])
        return result
    except Exception:
        logger.warning("LLM call failed", exc_info=True)
        return None
