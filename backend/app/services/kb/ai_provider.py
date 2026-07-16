"""AI drafting provider abstraction for the Knowledge Base.

The Response Workspace can draft with either the local Ollama model (default,
offline) or Anthropic's Claude API (optional cloud provider). This module owns
the provider vocabulary, provider-neutral error types, and a lightweight
in-process rate limiter shared by both providers.

The actual dispatch lives in ``drafting._generate_with_provider`` so the local
path still calls the module-level ``drafting.generate_text`` (which tests patch);
this module stays dependency-free and import-safe.
"""

from __future__ import annotations

import time
from collections import deque

PROVIDER_LOCAL = "local"
PROVIDER_CLAUDE = "claude"
PROVIDERS: tuple[str, ...] = (PROVIDER_LOCAL, PROVIDER_CLAUDE)

PROVIDER_LABELS: dict[str, str] = {
    PROVIDER_LOCAL: "Local (Ollama)",
    PROVIDER_CLAUDE: "Claude API (cloud)",
}


def resolve_provider(value: str | None) -> str:
    """Return a valid provider id, defaulting to the local model."""
    if value in PROVIDERS:
        return value  # type: ignore[return-value]
    return PROVIDER_LOCAL


# --- provider-neutral errors -------------------------------------------------


class DraftingError(RuntimeError):
    """Base for drafting-provider failures. Carries a user-safe message."""


class DraftingUnavailableError(DraftingError):
    """Provider is unavailable or not configured (maps to 503)."""


class DraftingTimeoutError(DraftingError):
    """Provider timed out (maps to 504)."""


class DraftingGenerateError(DraftingError):
    """Provider returned an error while generating (maps to 502)."""


class DraftingRateLimitError(DraftingError):
    """AI-generation rate limit exceeded (maps to 429)."""


# --- rate limiting -----------------------------------------------------------

# A generous fixed-window cap shared across providers. This is a local,
# single-user app, so the goal is only to stop a runaway loop (or a stuck UI)
# from hammering the local model or the paid cloud API — not multi-tenant
# fairness. Overridable in tests.
RATE_LIMIT_MAX = 60
RATE_LIMIT_WINDOW_SECONDS = 60.0
RATE_LIMIT_MESSAGE = (
    "AI generation rate limit reached. Please wait a moment and try again."
)

_events: deque[float] = deque()


def enforce_rate_limit() -> None:
    """Record one generation and raise if the window cap is exceeded."""
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    while _events and _events[0] < cutoff:
        _events.popleft()
    if len(_events) >= RATE_LIMIT_MAX:
        raise DraftingRateLimitError(RATE_LIMIT_MESSAGE)
    _events.append(now)


def reset_rate_limit() -> None:
    """Clear the rate-limit window (used by tests)."""
    _events.clear()
