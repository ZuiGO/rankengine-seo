"""Shared Groq token-budget limiter to avoid hammering the free-tier TPM cap.

All Groq callers (change generation, QA checks, chat) reserve a slice of the
per-minute token budget before calling; when the budget is exhausted the caller
waits for the window to reset instead of firing retries into 429s.
"""

import asyncio
import time

TOKEN_WINDOW = 60.0
TOKEN_BUDGET = 5500  # stay under the 6000 TPM free-tier cap
EST_TOKENS_PER_CALL = 450

_lock = asyncio.Lock()
_used = 0.0
_window_start = 0.0


async def acquire_token_budget(est_tokens: int = EST_TOKENS_PER_CALL) -> None:
    global _used, _window_start
    async with _lock:
        now = time.time()
        if now - _window_start >= TOKEN_WINDOW:
            _window_start = now
            _used = 0.0
        while _used + est_tokens > TOKEN_BUDGET:
            elapsed = now - _window_start
            await asyncio.sleep(TOKEN_WINDOW - elapsed + 0.1)
            now = time.time()
            if now - _window_start >= TOKEN_WINDOW:
                _window_start = now
                _used = 0.0
        _used += est_tokens
