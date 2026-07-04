"""NASA 3D — READY. The nasa3d.arc.nasa.gov collection is mirrored at
github.com/nasa/NASA-3D-Resources; we search it through the GitHub API.

Repo layout (verified live): visualization models as .glb under "3D Models/",
printable models as .stl under "3D Printing/", one subfolder per model.

No key required. GITHUB_TOKEN is optional and only raises the rate limit
(~60 req/hr unauthenticated → ~5,000 req/hr with a token). All content is
US-government public domain per NASA media usage guidelines.
"""
from __future__ import annotations

from urllib.parse import quote

from rich.console import Console

from models import DownloadTarget, ModelResult
from providers.base import ModelProvider

console = Console()

REPO = "nasa/NASA-3D-Resources"
BRANCH = "master"
MODEL_ROOTS = ("3D Models/", "3D Printing/")
MODEL_EXTENSIONS = [
    "glb", "stl", "blend", "3ds", "fbx", "lwo", "obj", "dae", "ply", "3mf",
    "stp", "step", "igs", "iges", "wrl", "gltf", "usdz",
]
LICENSE = "Public Domain (NASA media usage guidelines)"


class NasaProvider(ModelProvider):
    name = "NASA 3D"
    requires = []                      # works unauthenticated
    optional_env = ["GITHUB_TOKEN"]
    supports_filetype_filter = True
    notes = "GITHUB_TOKEN optional (raises GitHub rate limit)"

    def __init__(self, settings):
        super().__init__(settings)
        self._tree: list | None = None   # cached for the session

    def _auth(self) -> dict:
        token = self.settings.env.get("GITHUB_TOKEN")
        return {"Authorization": f"Bearer {token}"} if token else {}

    def available_filetypes(self) -> list[str]:
        return ["glb", "stl", "blend", "3ds", "fbx", "lwo"]

    def _load_tree(self) -> list:
        """One recursive tree call, cached; returns file paths under the model roots."""
        if self._tree is None:
            data = self._get_json(
                f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}",
                params={"recursive": "1"},
                headers=self._auth(),
            )
            if isinstance(data, dict) and data.get("truncated"):
                console.print(
                    "[yellow]Note: GitHub truncated the NASA repo listing, so results "
                    "may be incomplete. Set GITHUB_TOKEN to raise the rate limit.[/yellow]"
                )
            entries = data.get("tree", []) if isinstance(data, dict) else []
            self._tree = [
                e["path"]
                for e in entries
                if e.get("type") == "blob"
                and e.get("path", "").startswith(MODEL_ROOTS)
            ]
        return self._tree

    @staticmethod
    def _group_key(path: str) -> str:
        """Group files by '<root>/<model folder>' (e.g. '3D Printing/Apollo 11 - Landing Site')."""
        parts = path.split("/")
        return "/".join(parts[:2]) if len(parts) > 2 else path

    @staticmethod
    def _ext(path: str) -> str | None:
        name = path.rsplit("/", 1)[-1]
        return name.rsplit(".", 1)[-1].lower() if "." in name else None

    def search(self, query: str, file_type: str | None, limit: int) -> list[ModelResult]:
        tree = self._load_tree()
        query_lower = query.lower()

        groups: dict = {}   # '<root>/<model dir>' -> list of file paths
        for path in tree:
            # match against the path WITHOUT the collection root, else queries
            # like "models"/"printing"/"3d" would match every file in the repo
            searchable = path
            for root in MODEL_ROOTS:
                if path.startswith(root):
                    searchable = path[len(root):]
                    break
            if query_lower not in searchable.lower():
                continue
            groups.setdefault(self._group_key(path), []).append(path)

        results = []
        for group_key, paths in sorted(groups.items()):
            model_files = [p for p in paths if self._ext(p) in MODEL_EXTENSIONS]
            if not model_files:
                continue
            types = sorted({self._ext(p) for p in model_files if self._ext(p)})
            if file_type and file_type.lower() not in types:
                continue
            chosen = (
                [p for p in model_files if self._ext(p) == file_type.lower()]
                if file_type else model_files
            )
            title = group_key.split("/", 1)[-1]
            results.append(
                ModelResult(
                    provider=self.name,
                    id=group_key,
                    title=title,
                    author="NASA",
                    license=LICENSE,
                    page_url=f"https://github.com/{REPO}/tree/{BRANCH}/{quote(group_key)}",
                    file_types=types,
                    download_targets=[
                        DownloadTarget(
                            name=p.rsplit("/", 1)[-1],
                            url=f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{quote(p)}",
                            file_type=self._ext(p),
                        )
                        for p in chosen
                    ],
                )
            )
            if len(results) >= limit:
                break
        return results
