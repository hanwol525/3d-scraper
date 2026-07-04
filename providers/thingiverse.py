"""Thingiverse — READY. REST API with a Bearer app token.

Get a token at https://www.thingiverse.com/apps/create (an App Token is enough
for read access; no OAuth dance needed). Docs: https://www.thingiverse.com/developers
"""
from __future__ import annotations

from urllib.parse import quote

from rich.console import Console

from models import DownloadTarget, ModelResult
from providers.base import ModelProvider

console = Console()

API = "https://api.thingiverse.com"

# When a file-type filter is active we must fetch each thing's file list to
# know its types (the API has no server-side filter). Cap that fan-out to
# stay polite.
MAX_FILTER_HYDRATIONS = 10


class ThingiverseProvider(ModelProvider):
    name = "Thingiverse"
    requires = ["THINGIVERSE_TOKEN"]
    supports_filetype_filter = True
    notes = "App token from thingiverse.com/apps/create"

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.settings.env.get('THINGIVERSE_TOKEN', '')}"}

    def available_filetypes(self) -> list[str]:
        return ["stl", "obj", "3mf", "step", "scad", "amf", "gcode"]

    def search(self, query: str, file_type: str | None, limit: int) -> list[ModelResult]:
        data = self._get_json(
            f"{API}/search/{quote(query, safe='')}/",
            params={"type": "things", "page": 1, "per_page": limit},
            headers=self._auth(),
        )
        hits = data.get("hits", []) if isinstance(data, dict) else (data or [])
        results = []
        for hit in hits:
            if not isinstance(hit, dict) or not hit.get("id"):
                continue
            creator = hit.get("creator") or {}
            results.append(
                ModelResult(
                    provider=self.name,
                    id=str(hit["id"]),
                    title=hit.get("name") or f"thing {hit['id']}",
                    author=creator.get("name"),
                    page_url=hit.get("public_url") or f"https://www.thingiverse.com/thing:{hit['id']}",
                    license=hit.get("license"),   # human-readable string per Thing schema
                    thumbnail=hit.get("thumbnail"),
                )
            )

        if file_type:
            # No server-side filter: fetch file lists for the first few hits
            # and keep only things that actually contain that extension.
            checked = results[:MAX_FILTER_HYDRATIONS]
            if len(results) > MAX_FILTER_HYDRATIONS:
                console.print(
                    f"[dim]Filtering by .{file_type}: checked the first "
                    f"{MAX_FILTER_HYDRATIONS} of {len(results)} hits to stay within "
                    f"rate limits.[/dim]"
                )
            filtered = []
            for result in checked:
                hydrated = self.hydrate_downloads(result, file_type)
                if hydrated.download_targets:
                    filtered.append(hydrated)
            return filtered
        return results

    def hydrate_downloads(self, result: ModelResult, file_type: str | None = None) -> ModelResult:
        if result.license is None:
            thing = self._get_json(f"{API}/things/{result.id}", headers=self._auth())
            if isinstance(thing, dict):
                result.license = thing.get("license")
        files = self._get_json(f"{API}/things/{result.id}/files", headers=self._auth())
        targets, types = [], []
        for f in files or []:
            if not isinstance(f, dict):
                continue
            name = f.get("name") or ""
            # direct_url = CDN, no auth (nullable); download_url = tracked,
            # needs Bearer and 302-redirects to the file
            url = f.get("direct_url") or f.get("download_url") or f.get("public_url")
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else None
            if not url:
                continue
            if ext and ext not in types:
                types.append(ext)
            if file_type and ext != file_type.lower():
                continue
            targets.append(DownloadTarget(name=name, url=url, file_type=ext, size_bytes=f.get("size")))
        result.file_types = sorted(types)
        result.download_targets = targets
        return result

    def download_headers(self, url: str) -> dict:
        # Only api.thingiverse.com download_url endpoints need the Bearer token
        # (they 302-redirect to the file). direct_url points at the no-auth CDN,
        # so we must NOT send the app token there.
        if url.startswith("https://api.thingiverse.com/"):
            return self._auth()
        return {}
