"""Normalized data models shared by all providers."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DownloadTarget:
    name: str            # filename or label
    url: str             # direct download URL (may require auth header)
    file_type: str | None = None
    size_bytes: int | None = None


@dataclass
class ModelResult:
    provider: str
    id: str
    title: str
    author: str | None = None
    page_url: str | None = None
    license: str | None = None          # captured whenever the API exposes it
    thumbnail: str | None = None
    file_types: list[str] = field(default_factory=list)
    download_targets: list[DownloadTarget] = field(default_factory=list)
