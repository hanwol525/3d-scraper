"""Download files + write license/attribution sidecar metadata."""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TransferSpeedColumn,
)

from config import Settings
from http_utils import (
    BACKOFF_BASE_SECONDS,
    MAX_RETRIES,
    USER_AGENT,
    ProviderHTTPError,
    respect_rate_limit,
)
from models import DownloadTarget, ModelResult
from providers.base import ModelProvider

console = Console()


def safe_filename(name: str, fallback: str = "file") -> str:
    """Strip path separators / traversal / control characters from API-supplied
    names so a hostile filename can't escape the download directory."""
    name = unicodedata.normalize("NFKC", name)
    name = name.replace("\\", "/").split("/")[-1]          # drop any path component
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)             # control chars
    name = name.strip().strip(".")                          # no '.', '..', trailing dots
    name = re.sub(r"[<>:\"|?*]", "_", name)                 # windows-unfriendly chars
    return name or fallback


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len].rstrip("-") or "model"


def _unique_path(path: Path) -> Path:
    """Avoid silently overwriting an existing download."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 1000):
        candidate = path.with_name(f"{stem}-{i}{suffix}")
        if not candidate.exists():
            return candidate
    return path  # give up; overwrite rather than loop forever


def _write_sidecar(file_path: Path, result: ModelResult, target: DownloadTarget) -> None:
    meta = {
        "title": result.title,
        "author": result.author,
        "license": result.license,
        "source_page_url": result.page_url,
        "provider": result.provider,
        "download_url": target.url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    # route the sidecar through _unique_path too, so a real file literally named
    # "<x>.meta.json" isn't clobbered by (or clobbering) its neighbour's metadata
    sidecar = _unique_path(file_path.with_name(file_path.name + ".meta.json"))
    sidecar.write_text(json.dumps(meta, indent=2, ensure_ascii=False))


def download_result(result: ModelResult, provider: ModelProvider, settings: Settings) -> list[Path]:
    """Download every target of a result into downloads/<provider_slug>/<model-slug>/,
    each with a .meta.json sidecar. Returns the list of saved file paths."""
    if not result.download_targets:
        console.print("[yellow]This result has no downloadable files.[/yellow]")
        return []

    # short stable digest keeps folder names readable while avoiding collisions
    digest = hashlib.sha1(f"{result.provider}:{result.id}".encode()).hexdigest()[:8]
    dest_dir = settings.download_dir / provider.slug / f"{slugify(result.title)}-{digest}"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        console.print(f"[red]Couldn't create download folder {dest_dir}: {exc}[/red]")
        return []

    headers = {"User-Agent": USER_AGENT}

    saved: list[Path] = []
    for target in result.download_targets:
        dest = _unique_path(dest_dir / safe_filename(target.name))
        # attach provider auth only for this target's host (some hosts, e.g.
        # Thingiverse CDN URLs, must NOT receive the API token)
        target_headers = dict(headers)
        target_headers.update(provider.download_headers(target.url))
        try:
            _download_one(target.url, dest, target_headers, settings)
            _write_sidecar(dest, result, target)
        except (httpx.HTTPError, ProviderHTTPError, OSError) as exc:
            console.print(f"[red]✗ {target.name}: {exc}[/red]")
            continue
        saved.append(dest)
        console.print(f"[green]✓ saved[/green] {dest}")
    return saved


def _download_one(url: str, dest: Path, headers: dict, settings: Settings) -> None:
    """Rate-limited, retrying stream to a .part file, renamed into place only on
    success — so an interrupt (even Ctrl-C) never leaves a truncated final file."""
    provider_slug = dest.parent.parent.name
    part = dest.with_name(dest.name + ".part")
    last_error = "unknown error"
    for attempt in range(MAX_RETRIES + 1):
        respect_rate_limit(provider_slug, settings.rate_limit_delay)
        try:
            _stream_to_file(url, part, headers, settings.request_timeout, display_name=dest.name)
        except _RetryableStatus as exc:
            last_error = str(exc)
            part.unlink(missing_ok=True)
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE_SECONDS * (2 ** attempt))
                continue
            raise ProviderHTTPError(f"download failed: {last_error}")
        except BaseException:
            # includes KeyboardInterrupt: drop the partial file, then re-raise
            part.unlink(missing_ok=True)
            raise
        part.replace(dest)   # atomic on the same filesystem
        return
    raise ProviderHTTPError(f"download failed: {last_error}")


class _RetryableStatus(RuntimeError):
    pass


def _stream_to_file(url: str, dest: Path, headers: dict, timeout: float, display_name: str | None = None) -> None:
    with httpx.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=True) as response:
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableStatus(f"HTTP {response.status_code} while downloading {url}")
        if response.status_code >= 400:
            raise ProviderHTTPError(f"HTTP {response.status_code} while downloading {url}")
        total = int(response.headers.get("Content-Length") or 0) or None
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(display_name or dest.name, total=total)
            with open(dest, "wb") as fh:
                for chunk in response.iter_bytes(chunk_size=65536):
                    fh.write(chunk)
                    progress.update(task, advance=len(chunk))
