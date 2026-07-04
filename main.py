"""Interactive CLI entry point: pick a source, search, view results, download.

Also supports non-interactive flags for scripted runs:
    python main.py --provider "NASA 3D" --query apollo --filetype stl --download 1
"""
from __future__ import annotations

import argparse
import sys

import questionary
from rich.console import Console
from rich.table import Table

from config import Settings, load_settings
from downloader import download_result
from http_utils import ProviderHTTPError
from models import ModelResult
from providers.base import ModelProvider, ProviderNotReady
from registry import build_registry

console = Console()
DEFAULT_LIMIT = 20


# ---------------------------------------------------------------- rendering

def render_results(results: list[ModelResult]) -> None:
    table = Table(title=f"{len(results)} result(s)", show_lines=False)
    table.add_column("#", justify="right", style="bold")
    table.add_column("Title", overflow="fold", max_width=48)
    table.add_column("Author")
    table.add_column("License", overflow="fold", max_width=28)
    table.add_column("File types")
    for i, r in enumerate(results, start=1):
        table.add_row(
            str(i),
            r.title,
            r.author or "—",
            r.license or "—",
            ", ".join(r.file_types) if r.file_types else "—",
        )
    console.print(table)


def _target_label(target) -> str:
    size = ""
    if target.size_bytes:
        size = f"  ({target.size_bytes / 1_048_576:.1f} MB)"
    return f"{target.name}{size}"


def show_download_summary(result: ModelResult) -> None:
    if result.license:
        console.print(f"[bold]License:[/bold] {result.license} — a .meta.json sidecar records this for attribution.")
    else:
        console.print("[yellow]No license info exposed by the API — check the source page before reusing.[/yellow]")
    if result.page_url:
        console.print(f"[bold]Source page:[/bold] {result.page_url}")


# ---------------------------------------------------------------- one search pass

def run_search(
    provider: ModelProvider,
    query: str,
    file_type: str | None,
    limit: int,
) -> list[ModelResult]:
    with console.status(f"Searching {provider.name} for “{query}”…"):
        return provider.search(query, file_type, limit)


def handle_selection(
    provider: ModelProvider,
    result: ModelResult,
    file_type: str | None,
    settings: Settings,
    interactive: bool = False,
) -> None:
    if provider.search_only:
        console.print("\nThis source is a meta-search: it links out to other sites rather than hosting files.")
        console.print(f"Open in your browser: [link]{result.page_url}[/link]\n")
        return
    if not result.download_targets:
        with console.status("Fetching file list…"):
            result = provider.hydrate_downloads(result, file_type)
    if not result.download_targets:
        console.print("[yellow]No downloadable files found for this result"
                      + (f" with type “{file_type}”." if file_type else ".") + "[/yellow]")
        return
    show_download_summary(result)
    if interactive and len(result.download_targets) > 1:
        picked = questionary.checkbox(
            f"{len(result.download_targets)} files available — pick which to download:",
            choices=[
                questionary.Choice(title=_target_label(t), value=i, checked=False)
                for i, t in enumerate(result.download_targets)
            ],
        ).ask()
        if not picked:
            console.print("Nothing selected — skipping download.\n")
            return
        result.download_targets = [result.download_targets[i] for i in picked]
    else:
        names = ", ".join(t.name for t in result.download_targets[:8])
        more = "" if len(result.download_targets) <= 8 else f" (+{len(result.download_targets) - 8} more)"
        console.print(f"[bold]Files:[/bold] {names}{more}")
    saved = download_result(result, provider, settings)
    if saved:
        console.print(f"\n[green bold]Done[/green bold] — {len(saved)} file(s) in {saved[0].parent}\n")


# ---------------------------------------------------------------- interactive loop

def pick_provider(registry: dict, settings: Settings) -> ModelProvider | None:
    choices = []
    for provider in registry.values():
        label = provider.status_label(settings.env)
        marker = "✓" if provider.is_usable(settings.env) else "•"
        title = f"{marker} {provider.name}  ({label})"
        choices.append(questionary.Choice(title=title, value=provider.name))
    choices.append(questionary.Choice(title="✗ Quit", value="__quit__"))
    picked = questionary.select("Which source do you want to search?", choices=choices).ask()
    # picked is None on Ctrl-C/Esc, "__quit__" on the Quit item → both mean stop
    return registry.get(picked) if picked and picked != "__quit__" else None


def pick_filetype(provider: ModelProvider) -> str | None:
    if not provider.supports_filetype_filter:
        return None
    options = ["Any"] + provider.available_filetypes()
    picked = questionary.select("Filter by file type?", choices=options).ask()
    if picked is None:
        raise KeyboardInterrupt
    return None if picked == "Any" else picked.lower()


def pick_result(results: list[ModelResult]) -> ModelResult | None:
    # NB: questionary replaces value=None with the choice's title string, so a
    # "back" option must use a real sentinel, not None (which also = cancel).
    choices = [
        questionary.Choice(title=f"{i}. {r.title}" + (f" — {r.author}" if r.author else ""), value=i - 1)
        for i, r in enumerate(results, start=1)
    ]
    choices.append(questionary.Choice(title="None — back to menu", value=-1))
    picked = questionary.select("Download one of these?", choices=choices).ask()
    if isinstance(picked, int) and picked >= 0:
        return results[picked]
    return None   # -1 (back) or None (Ctrl-C / Esc)


def explain_not_ready(provider: ModelProvider, settings: Settings) -> None:
    console.print(f"\n[yellow bold]{provider.name} isn't usable yet.[/yellow bold]")
    if not provider.implemented:
        console.print(provider.notes or "Its API could not be verified; see README for status.")
    else:
        missing = [k for k in provider.requires if not settings.env.get(k)]
        console.print("Add to your .env: " + ", ".join(missing))
        if provider.notes:
            console.print(provider.notes)
    console.print()


def interactive_loop(registry: dict, settings: Settings) -> None:
    console.print("[bold cyan]3D Model Fetcher[/bold cyan] — search public repositories, download with attribution.\n")
    while True:
        provider = pick_provider(registry, settings)
        if provider is None:
            console.print("Bye! 👋")
            return
        if not provider.is_usable(settings.env):
            explain_not_ready(provider, settings)
            continue

        query = questionary.text("Search query:").ask()
        if not query or not query.strip():
            continue
        query = query.strip()

        try:
            file_type = pick_filetype(provider)
        except KeyboardInterrupt:
            continue

        try:
            results = run_search(provider, query, file_type, DEFAULT_LIMIT)
        except (ProviderHTTPError, ProviderNotReady) as exc:
            console.print(f"[red]Search failed:[/red] {exc}\n")
            continue
        except Exception as exc:  # keep the loop alive on provider bugs
            console.print(f"[red]Unexpected error from {provider.name}:[/red] {exc}\n")
            continue

        if not results:
            console.print(f"No results on {provider.name} for “{query}”"
                          + (f" with file type “{file_type}”" if file_type else "") + ".\n")
            continue

        render_results(results)
        selection = pick_result(results)
        if selection is not None:
            try:
                handle_selection(provider, selection, file_type, settings, interactive=True)
            except (ProviderHTTPError, ProviderNotReady) as exc:
                console.print(f"[red]Download failed:[/red] {exc}\n")
            except Exception as exc:
                console.print(f"[red]Unexpected error:[/red] {exc}\n")

        if not questionary.confirm("Search again?", default=True).ask():
            console.print("Bye! 👋")
            return


# ---------------------------------------------------------------- scripted mode

def scripted_run(args: argparse.Namespace, registry: dict, settings: Settings) -> int:
    provider = None
    for p in registry.values():
        if p.name.lower() == args.provider.lower() or p.slug == args.provider.lower():
            provider = p
            break
    if provider is None:
        console.print(f"[red]Unknown provider “{args.provider}”.[/red] Known: "
                      + ", ".join(p.name for p in registry.values()))
        return 2
    if not provider.is_usable(settings.env):
        explain_not_ready(provider, settings)
        return 2
    file_type = args.filetype.lower() if args.filetype else None
    try:
        results = run_search(provider, args.query, file_type, args.limit)
    except (ProviderHTTPError, ProviderNotReady) as exc:
        console.print(f"[red]Search failed:[/red] {exc}")
        return 1
    except Exception as exc:   # a provider bug shouldn't dump a traceback
        console.print(f"[red]Unexpected error from {provider.name}:[/red] {exc}")
        return 1
    if not results:
        console.print("No results.")
        return 0
    render_results(results)
    if args.download is not None:
        if not 1 <= args.download <= len(results):
            console.print(f"[red]--download must be between 1 and {len(results)}[/red]")
            return 2
        try:
            handle_selection(provider, results[args.download - 1], file_type, settings)
        except (ProviderHTTPError, ProviderNotReady) as exc:
            console.print(f"[red]Download failed:[/red] {exc}")
            return 1
        except Exception as exc:
            console.print(f"[red]Unexpected error:[/red] {exc}")
            return 1
    return 0


def list_providers(registry: dict, settings: Settings) -> None:
    table = Table(title="Providers")
    table.add_column("Provider")
    table.add_column("Status")
    table.add_column("File-type filter")
    for p in registry.values():
        table.add_row(
            p.name,
            p.status_label(settings.env),
            "yes" if p.supports_filetype_filter else "no",
        )
    console.print(table)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch 3D models from public repositories.")
    parser.add_argument("--provider", help="provider name (skips the interactive picker)")
    parser.add_argument("--query", help="search query")
    parser.add_argument("--filetype", help="file type filter, e.g. stl")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="max results")
    parser.add_argument("--download", type=int, metavar="N", help="download result #N (1-based)")
    parser.add_argument("--list-providers", action="store_true", help="print provider status and exit")
    args = parser.parse_args()

    settings = load_settings()
    registry = build_registry(settings)

    try:
        if args.list_providers:
            list_providers(registry, settings)
            return 0
        if args.provider and args.query:
            return scripted_run(args, registry, settings)
        if args.provider or args.query:
            parser.error("--provider and --query must be used together")
        interactive_loop(registry, settings)
    except (KeyboardInterrupt, EOFError):
        console.print("\nBye! 👋")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
