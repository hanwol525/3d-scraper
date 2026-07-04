"""Smithsonian — two providers, both verified live (2026-07-03):

1. Smithsonian 3D  (3d-api.si.edu, alpha) — NO API KEY NEEDED. One endpoint,
   GET /api/v1.0/content/file/search, with server-side file_type/model_type
   filters; results carry directly downloadable content.uri values. CC0.

2. Smithsonian Open Access  (api.si.edu) — needs a free api.data.gov key.
   Searches full collection records; 3D media entries have type "3d_voyager"
   and their downloadable files live in the entry's resources[] array
   (the "content" URL is an HTML viewer page, not a file). CC0.
"""
from __future__ import annotations

from models import DownloadTarget, ModelResult
from providers.base import ModelProvider

THREE_D_API = "https://3d-api.si.edu/api/v1.0/content/file/search"
OPEN_ACCESS_API = "https://api.si.edu/openaccess/api/v1.0"
CC0 = "CC0 (Smithsonian Open Access)"

MODEL_FILE_EXTENSIONS = ("glb", "gltf", "obj", "stl", "usdz", "ply", "blend", "f3z", "x3d", "fbx")


def _filename(url: str) -> str:
    return url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]


def _url_ext(url: str) -> str | None:
    tail = _filename(url)
    return tail.rsplit(".", 1)[-1].lower() if "." in tail else None


class Smithsonian3dProvider(ModelProvider):
    """Dedicated 3D API — key-free, server-side filters, direct file URLs."""

    name = "Smithsonian 3D"
    requires = []
    supports_filetype_filter = True
    notes = "No key needed (alpha API)"

    # file_type is a per-file filter (glb|ply|zip); other values filter by the
    # package's model_type (both verified in the live apiDoc definition).
    FILE_TYPE_VALUES = ("glb", "ply", "zip")
    MODEL_TYPE_VALUES = ("obj", "stl", "gltf", "blend", "f3z")

    def available_filetypes(self) -> list[str]:
        return list(self.FILE_TYPE_VALUES) + list(self.MODEL_TYPE_VALUES)

    def search(self, query: str, file_type: str | None, limit: int) -> list[ModelResult]:
        params = {"q": query}
        if file_type:
            if file_type in self.FILE_TYPE_VALUES:
                params["file_type"] = file_type
            else:
                params["model_type"] = file_type
        # The API returns one row PER FILE and defaults to just 10 rows; a single
        # package spans ~10 files, so without a large `rows` we'd get ~1 result.
        params["rows"] = min(max(limit * 12, 60), 1000)
        data = self._get_json(THREE_D_API, params=params)
        rows = (data or {}).get("rows") or []

        # One row per file; group rows into one result per 3D package.
        packages: dict = {}
        order: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            content = row.get("content") or {}
            package_id = content.get("model_url") or row.get("title") or "unknown"
            if package_id not in packages:
                packages[package_id] = {"title": row.get("title") or "(untitled)", "rows": []}
                order.append(package_id)
            packages[package_id]["rows"].append(content)

        results = []
        for package_id in order[: limit * 3]:
            info = packages[package_id]
            targets, types, thumbnail = [], [], None
            # same asset can appear on multiple rows (Web3D/Download3D usages,
            # root + /resources/ paths); dedupe by filename, keeping file_size
            by_name = {}
            for content in info["rows"]:
                uri = content.get("uri")
                if not uri:
                    continue
                fname = _filename(uri)
                if fname in by_name:
                    if content.get("file_size") and not by_name[fname].get("file_size"):
                        by_name[fname] = content
                    continue
                by_name[fname] = content
            for content in by_name.values():
                uri = content["uri"]
                ftype = (content.get("file_type") or _url_ext(uri) or "").lower()
                if ftype == "jpg":
                    thumbnail = thumbnail or uri
                    continue
                label = _filename(uri)
                quality = content.get("quality")
                if quality:
                    label = f"{label} ({quality})"
                if ftype and ftype not in types:
                    types.append(ftype)
                targets.append(
                    DownloadTarget(
                        name=_filename(uri),
                        url=uri,
                        file_type=ftype or None,
                        size_bytes=content.get("file_size"),
                    )
                )
            if not targets:
                continue
            # model_url looks like "3d_package:<uuid>"; the Voyager viewer page
            # (verified 200) drops the prefix.
            page_url = None
            if isinstance(package_id, str) and package_id.startswith("3d_package:"):
                page_url = f"https://3d-api.si.edu/voyager/{package_id.split(':', 1)[1]}"
            results.append(
                ModelResult(
                    provider=self.name,
                    id=str(package_id),
                    title=info["title"],
                    author="Smithsonian Institution",
                    page_url=page_url,
                    license=CC0,
                    thumbnail=thumbnail,
                    file_types=sorted(types),
                    download_targets=targets,
                )
            )
            if len(results) >= limit:
                break
        return results


class SmithsonianOpenAccessProvider(ModelProvider):
    """Open Access collection search — richer records, needs a free key."""

    name = "Smithsonian Open Access"
    requires = ["SMITHSONIAN_API_KEY"]
    supports_filetype_filter = True
    notes = "Free key from api.data.gov/signup"

    def available_filetypes(self) -> list[str]:
        return list(MODEL_FILE_EXTENSIONS)

    def _key(self) -> str:
        return self.settings.env.get("SMITHSONIAN_API_KEY", "")

    def search(self, query: str, file_type: str | None, limit: int) -> list[ModelResult]:
        # Filters are fielded terms inside q (there is no separate fq param);
        # online_media_type:"3D Models" is the exact vocabulary term.
        data = self._get_json(
            f"{OPEN_ACCESS_API}/search",
            params={
                "q": f'({query}) AND online_media_type:"3D Models"',
                "start": 0,
                "rows": min(max(limit * 2, 20), 1000),   # API allows up to 1000
                "api_key": self._key(),
            },
        )
        rows = (((data or {}).get("response") or {}).get("rows")) or []
        results = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            result = self._row_to_result(row, file_type)
            if result is not None:
                results.append(result)
            if len(results) >= limit:
                break
        return results

    def _row_to_result(self, row: dict, file_type: str | None) -> ModelResult | None:
        content = row.get("content") or {}
        descriptive = content.get("descriptiveNonRepeating") or {}
        media_list = ((descriptive.get("online_media") or {}).get("media")) or []

        media_3d = [
            m for m in media_list
            if isinstance(m, dict) and "3d" in str(m.get("type", "")).lower()
        ]
        if not media_3d:
            return None

        targets, types, thumbnail = [], [], None
        for media in media_3d:
            thumbnail = thumbnail or media.get("thumbnail")
            # media["content"] is an HTML viewer page; real files are resources[]
            for resource in media.get("resources") or []:
                if not isinstance(resource, dict) or not resource.get("url"):
                    continue
                url = str(resource["url"])
                name = resource.get("filename") or _filename(url)
                ext = (name.rsplit(".", 1)[-1].lower() if "." in name else None) or _url_ext(url)
                if ext not in MODEL_FILE_EXTENSIONS:
                    continue
                if ext not in types:
                    types.append(ext)
                if file_type and ext != file_type.lower():
                    continue
                targets.append(DownloadTarget(name=name, url=url, file_type=ext))

        if not targets:
            return None

        freetext = content.get("freetext") or {}
        names = freetext.get("name") or []
        author = names[0].get("content") if names and isinstance(names[0], dict) else None

        usage = (descriptive.get("metadata_usage") or {})
        license_label = usage.get("access") or CC0

        return ModelResult(
            provider=self.name,
            id=str(row.get("id", "")),
            title=row.get("title") or "(untitled)",
            author=author,
            page_url=descriptive.get("record_link") or descriptive.get("guid"),
            license=license_label,
            thumbnail=thumbnail,
            file_types=sorted(types),
            download_targets=targets,
        )
