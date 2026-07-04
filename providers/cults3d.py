"""Cults3D — GATED (self-serve). GraphQL API verified live (2026-07-03):
POST https://cults3d.com/graphql with HTTP Basic auth (your Cults username +
an API key generated at https://cults3d.com/en/api/keys).

By design the API does NOT expose other users' model files ("they remain
hosted on Cults for legal reasons"), so this provider is search-only: it
returns rich metadata + the creation's page URL for browser download.
"""
from __future__ import annotations

from models import ModelResult
from providers.base import ModelProvider, ProviderNotReady

GRAPHQL_URL = "https://cults3d.com/graphql"

SEARCH_QUERY = """
query Search($q: String!, $limit: Int!) {
  creationsSearchBatch(query: $q, limit: $limit) {
    total
    results {
      name(locale: EN)
      shortUrl
      illustrationImageUrl
      license { name(locale: EN) }
      creator { nick shortUrl }
    }
  }
}
"""


class Cults3dProvider(ModelProvider):
    name = "Cults3D"
    requires = ["CULTS3D_USERNAME", "CULTS3D_API_KEY"]
    search_only = True   # API exposes metadata + page links, never others' files
    notes = "Key self-serve at cults3d.com/en/api/keys; files must be fetched via the website"

    def search(self, query: str, file_type: str | None, limit: int) -> list[ModelResult]:
        auth = (
            self.settings.env.get("CULTS3D_USERNAME", ""),
            self.settings.env.get("CULTS3D_API_KEY", ""),
        )
        data = self._post_json(
            GRAPHQL_URL,
            json_body={"query": SEARCH_QUERY, "variables": {"q": query, "limit": limit}},
            auth=auth,
        )
        if data.get("errors"):
            message = "; ".join(str(e.get("message", e)) for e in data["errors"][:3])
            raise ProviderNotReady(f"Cults3D GraphQL error: {message}")
        batch = ((data.get("data") or {}).get("creationsSearchBatch")) or {}
        results = []
        for creation in batch.get("results") or []:
            if not isinstance(creation, dict):
                continue
            creator = creation.get("creator") or {}
            license_info = creation.get("license") or {}
            page_url = creation.get("shortUrl")
            results.append(
                ModelResult(
                    provider=self.name,
                    id=page_url or creation.get("name") or "?",
                    title=creation.get("name") or "(untitled)",
                    author=creator.get("nick"),
                    page_url=page_url,
                    license=license_info.get("name"),
                    thumbnail=creation.get("illustrationImageUrl"),
                )
            )
        return results
