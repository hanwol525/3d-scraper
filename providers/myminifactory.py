"""MyMiniFactory — GATED. API v2 verified live (2026-07-03) via the official
OpenAPI spec (github.com/MyMiniFactory/api-documentation). API keys are created
self-serve in your MyMiniFactory account settings.

Important limitation from the spec: File.download_url and
Object.archive_download_url are available ONLY to an OAuth-connected user,
NOT with a plain API key. So this provider searches and shows metadata, and
points you at the model page to download in a browser.
"""
from __future__ import annotations

from http_utils import ProviderHTTPError
from models import DownloadTarget, ModelResult
from providers.base import ModelProvider, ProviderNotReady

API = "https://www.myminifactory.com/api/v2"


class MyMiniFactoryProvider(ModelProvider):
    name = "MyMiniFactory"
    requires = ["MYMINIFACTORY_API_KEY"]
    supports_filetype_filter = False   # no server-side filter; files only visible per-object
    notes = "API key = search/metadata only; downloads need the website (OAuth not implemented)"

    def _key(self) -> str:
        return self.settings.env.get("MYMINIFACTORY_API_KEY", "")

    def search(self, query: str, file_type: str | None, limit: int) -> list[ModelResult]:
        data = self._get_json(
            f"{API}/search",
            params={"q": query, "key": self._key(), "per_page": limit, "page": 1},
        )
        items = (data or {}).get("items") or []
        results = []
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            designer = item.get("designer") or {}
            images = item.get("images") or []
            thumbnail = None
            if images and isinstance(images[0], dict):
                thumbnail = ((images[0].get("original") or {}).get("url"))
            license_label = item.get("license")
            if not license_label:
                licenses = item.get("licenses") or []
                if licenses and isinstance(licenses[0], dict):
                    license_label = licenses[0].get("value") or licenses[0].get("type")
            results.append(
                ModelResult(
                    provider=self.name,
                    id=str(item["id"]),
                    title=item.get("name") or f"object {item['id']}",
                    author=designer.get("username") or designer.get("name"),
                    page_url=item.get("url"),
                    license=license_label,
                    thumbnail=thumbnail,
                )
            )
        return results

    def hydrate_downloads(self, result: ModelResult, file_type: str | None = None) -> ModelResult:
        try:
            data = self._get_json(
                f"{API}/objects/{result.id}/files",
                params={"key": self._key()},
            )
        except ProviderHTTPError as exc:
            raise ProviderNotReady(f"couldn't list files for this object: {exc}")
        files = (data or {}).get("items") or []
        targets, types = [], []
        for f in files:
            if not isinstance(f, dict):
                continue
            filename = f.get("filename") or ""
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else None
            if ext and ext not in types:
                types.append(ext)
            url = f.get("download_url")   # present only for OAuth-connected users
            if not url:
                continue
            if file_type and ext != file_type.lower():
                continue
            targets.append(DownloadTarget(name=filename, url=url, file_type=ext))
        result.file_types = sorted(types)
        result.download_targets = targets
        if files and not targets:
            raise ProviderNotReady(
                "MyMiniFactory API keys allow search/metadata only — file downloads "
                "require an OAuth-connected user, which this CLI doesn't implement. "
                f"Download in your browser instead: {result.page_url}"
            )
        return result
