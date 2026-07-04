"""ModelProvider base class — every source implements this interface."""
from __future__ import annotations

import re

from config import Settings
from http_utils import ProviderHTTPError, polite_get, polite_request
from models import ModelResult


class ProviderNotReady(RuntimeError):
    """Raised when a provider can't be used yet (missing key / not implemented).
    The message explains what's needed."""


class ModelProvider:
    name: str = "?"                      # e.g. "Thingiverse"
    requires: list[str] = []             # env var names this provider needs
    optional_env: list[str] = []         # env vars that help but aren't required
    supports_filetype_filter: bool = False
    implemented: bool = True             # False for scaffolds awaiting API verification
    search_only: bool = False            # True for meta-search sources that link out
    notes: str = ""                      # short status hint shown in the picker
    unimplemented_label: str = "not yet implemented"

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_")

    def is_configured(self, env: dict) -> bool:
        return all(env.get(k) for k in self.requires)

    def status_label(self, env: dict) -> str:
        """Human-readable availability marker for the provider picker."""
        if not self.implemented:
            return self.unimplemented_label
        if not self.is_configured(env):
            missing = [k for k in self.requires if not env.get(k)]
            return "needs " + ", ".join(missing)
        if self.search_only:
            return "ready — search-only, links out"
        return "ready"

    def is_usable(self, env: dict) -> bool:
        return self.implemented and self.is_configured(env)

    def available_filetypes(self) -> list[str]:
        return []

    def search(self, query: str, file_type: str | None, limit: int) -> list[ModelResult]:
        raise NotImplementedError

    def hydrate_downloads(self, result: ModelResult, file_type: str | None = None) -> ModelResult:
        """Populate download_targets lazily if search() didn't."""
        return result

    def download_headers(self, url: str) -> dict:
        """Extra headers needed when fetching a specific download URL. Providers
        should return auth headers ONLY for hosts that require them, so tokens
        aren't leaked to third-party/CDN hosts."""
        return {}

    # -- shared HTTP helper -------------------------------------------------

    def _get(self, url: str, *, headers: dict | None = None, params: dict | None = None):
        return polite_get(
            url,
            provider_slug=self.slug,
            rate_limit_delay=self.settings.rate_limit_delay,
            timeout=self.settings.request_timeout,
            headers=headers,
            params=params,
        )

    @staticmethod
    def _parse_json(response, url: str):
        try:
            return response.json()
        except ValueError:  # JSONDecodeError subclasses ValueError
            raise ProviderHTTPError(
                f"expected JSON from {url} but got {response.headers.get('content-type', 'unknown')} "
                "(the service may be down or returning an error page)"
            )

    def _get_json(self, url: str, *, headers: dict | None = None, params: dict | None = None):
        response = self._get(url, headers=headers, params=params)
        return self._parse_json(response, url)

    def _post_json(self, url: str, *, json_body: dict, headers: dict | None = None, auth: tuple | None = None):
        response = polite_request(
            "POST",
            url,
            provider_slug=self.slug,
            rate_limit_delay=self.settings.rate_limit_delay,
            timeout=self.settings.request_timeout,
            headers=headers,
            json_body=json_body,
            auth=auth,
        )
        return self._parse_json(response, url)
