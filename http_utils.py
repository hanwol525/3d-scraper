"""Shared HTTP plumbing: descriptive UA, timeouts, per-provider rate limiting,
and retry with exponential backoff on 429/5xx."""
from __future__ import annotations

import random
import time

import httpx

USER_AGENT = "3d-model-fetcher/0.1 (interactive CLI; github.com/local-use)"

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.5

# provider slug -> monotonic time of last request, for polite pacing
_last_request_at: dict = {}


class ProviderHTTPError(RuntimeError):
    """Raised when a request fails after retries; message is user-readable."""


def respect_rate_limit(provider_slug: str, delay: float) -> None:
    """Public entry point so streaming downloads share the same per-provider pacing."""
    _respect_rate_limit(provider_slug, delay)


def _respect_rate_limit(provider_slug: str, delay: float) -> None:
    last = _last_request_at.get(provider_slug)
    now = time.monotonic()
    if last is not None:
        wait = delay - (now - last)
        if wait > 0:
            time.sleep(wait)
    _last_request_at[provider_slug] = time.monotonic()


def _retry_wait(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                # clamp: a malformed/negative value must never reach time.sleep()
                return max(0.0, min(float(retry_after), 60.0))
            except ValueError:
                pass   # HTTP-date form → fall through to exponential backoff
    return BACKOFF_BASE_SECONDS * (2 ** attempt) + random.uniform(0, 0.5)


def polite_request(
    method: str,
    url: str,
    *,
    provider_slug: str,
    rate_limit_delay: float,
    timeout: float,
    headers: dict | None = None,
    params: dict | None = None,
    json_body: dict | None = None,
    auth: tuple | None = None,
    follow_redirects: bool = True,
) -> httpx.Response:
    """Request with rate limiting, UA, timeout, and backoff retries. Raises
    ProviderHTTPError with a readable message on failure."""
    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)

    last_error: str = "unknown error"
    for attempt in range(MAX_RETRIES + 1):
        _respect_rate_limit(provider_slug, rate_limit_delay)
        try:
            response = httpx.request(
                method,
                url,
                params=params,
                json=json_body,
                auth=auth,
                headers=merged_headers,
                timeout=timeout,
                follow_redirects=follow_redirects,
            )
        except httpx.TimeoutException:
            last_error = f"request timed out after {timeout:.0f}s"
            response = None
        except httpx.HTTPError as exc:
            last_error = f"network error: {exc}"
            response = None

        if response is not None:
            if response.status_code < 400:
                return response
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code} from {response.request.url.host}"
            else:
                # 4xx other than 429: retrying won't help
                raise ProviderHTTPError(
                    f"HTTP {response.status_code} for {url} — {_short_body(response)}"
                )

        if attempt < MAX_RETRIES:
            time.sleep(_retry_wait(response, attempt))

    raise ProviderHTTPError(f"giving up on {url} after {MAX_RETRIES + 1} attempts ({last_error})")


def polite_get(url: str, **kwargs) -> httpx.Response:
    return polite_request("GET", url, **kwargs)


def _short_body(response: httpx.Response) -> str:
    try:
        text = response.text.strip()
    except Exception:
        return "(unreadable body)"
    return (text[:200] + "…") if len(text) > 200 else (text or "(empty body)")
