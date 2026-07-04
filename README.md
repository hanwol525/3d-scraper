# 3D Model Fetcher

An interactive CLI that searches multiple public 3D-model repositories through
their official APIs and downloads models with license/attribution metadata
preserved alongside every file.

```
$ python main.py
? Which source do you want to search?
  ✓ Smithsonian 3D      (ready)
  ✓ NASA 3D             (ready)
  • Thingiverse         (needs THINGIVERSE_TOKEN)
  ...
```

**Two sources work with zero configuration** (NASA 3D and Smithsonian 3D — no
API keys needed). The rest activate as you add keys to `.env`.

## Setup

```bash
python3 -m venv venv                # Python 3.9+ (tested on 3.9.6)
./venv/bin/pip install -r requirements.txt
cp .env.example .env                # then fill in whichever keys you have
./venv/bin/python main.py
```

Scripted (non-interactive) mode:

```bash
python main.py --list-providers
python main.py --provider "NASA 3D" --query apollo --filetype stl
python main.py --provider "Smithsonian 3D" --query crab --filetype glb --download 1
```

## Provider status

Verified against each source's live API docs on 2026-07-03.

| Provider | Status | Key needed | File-type filter |
|---|---|---|---|
| **Smithsonian 3D** (3d-api.si.edu) | ✅ working | none | server-side (`file_type`/`model_type`) |
| **NASA 3D** (GitHub mirror) | ✅ working | none (`GITHUB_TOKEN` optional, raises rate limit) | client-side |
| **Smithsonian Open Access** | ✅ working | free — [api.data.gov/signup](https://api.data.gov/signup/) | client-side |
| **Thingiverse** | ✅ implemented (add token) | free — [thingiverse.com/apps/create](https://www.thingiverse.com/apps/create) | client-side |
| **MyMiniFactory** | 🔍 search/metadata only¹ | self-serve, account settings | — |
| **Cults3D** | 🔍 search only² | self-serve — [cults3d.com/en/api/keys](https://cults3d.com/en/api/keys) | — |
| Yeggi | ❌ no API exists³ | — | — |
| GrabCAD | ❌ no library API³ | — | — |
| YouMagine | ❌ API defunct³ | — | — |
| Thangs | ❌ no public API³ | — | — |
| NIH 3D | ❌ API retired³ | — | — |

¹ MyMiniFactory's spec is explicit: `download_url` is available **only to an
OAuth-connected user**, not with an API key. This CLI implements the key flow
(search + file listing) and links you to the model page to download.

² Cults3D's API intentionally never exposes other users' model files ("they
remain hosted on Cults for legal reasons") — the provider returns metadata,
license, and the page link.

³ Verified against live docs/probes on 2026-07-03, not guessed: Yeggi has no
API in any form (and bot-challenges scripts); GrabCAD's Workbench API was shut
down in June 2023 and nothing covers the library; YouMagine's api.youmagine.com
no longer resolves in DNS (acquired by MyMiniFactory, 2024); Thangs has no
public API and its content policy prohibits scraping; NIH 3D's old public API
was retired and the rebuilt site exposes no JSON search endpoint. Each is an
honest `NotImplementedError` stub in `providers/scaffolds.py` so it can be
slotted in if an API ever (re)appears.

### Getting keys for the ready providers

- **Thingiverse** — create an app at
  [thingiverse.com/apps/create](https://www.thingiverse.com/apps/create); the
  issued **App Token** works directly as a Bearer token for read access (no
  OAuth flow). Put it in `THINGIVERSE_TOKEN`. Rate limit: 300 requests per
  5-minute window.
- **Smithsonian Open Access** — free instant key from
  [api.data.gov/signup](https://api.data.gov/signup/) → `SMITHSONIAN_API_KEY`
  (1,000 requests/hour). `DEMO_KEY` works for a quick try at a much lower limit.
- **NASA 3D** — no key. Optionally set `GITHUB_TOKEN` (any GitHub personal
  access token, no scopes needed) to raise the GitHub API limit from ~60 to
  ~5,000 requests/hour.
- **Smithsonian 3D** — no key at all. Note the API is labeled *alpha* by the
  Smithsonian, so its response format may change.

## What gets downloaded

Files land in `downloads/<provider>/<model-slug>-<id>/`. Next to every file the
tool writes `<filename>.meta.json`:

```json
{
  "title": "Apollo 11 - Landing Site",
  "author": "NASA",
  "license": "Public Domain (NASA media usage guidelines)",
  "source_page_url": "https://github.com/nasa/NASA-3D-Resources/tree/master/...",
  "provider": "NASA 3D",
  "download_url": "https://raw.githubusercontent.com/...",
  "retrieved_at": "2026-07-03T21:30:05+00:00"
}
```

**Free to download ≠ free to reuse.** CC-BY requires attribution, NC licenses
forbid selling prints, CC0/public-domain is unrestricted. The sidecar captures
the license at download time so you can honor it later instead of guessing.

## Responsible fetching

Built in, not optional:

- Per-provider rate limiting (`RATE_LIMIT_DELAY_SECONDS`, default 1s between requests).
- Retries with exponential backoff on 429/5xx, honoring `Retry-After`.
- `REQUEST_TIMEOUT_SECONDS` on every request; descriptive `User-Agent`.
- Filenames from APIs are sanitized before writing to disk.
- On-demand fetching only — the tool downloads what you select, nothing in bulk.
  Review each source's terms before automating heavier access. Thingiverse's API
  terms in particular prohibit redistributing its content or scraping.

## Architecture

Each source is one class in `providers/` implementing `ModelProvider`
(`search()`, `hydrate_downloads()`, optional `download_headers()`), returning
normalized `ModelResult`/`DownloadTarget` dataclasses. `registry.py` assembles
the picker list — add or remove a provider without touching the CLI.

```
main.py          questionary flow + scripted flags
config.py        .env → Settings
models.py        ModelResult / DownloadTarget
registry.py      provider list
downloader.py    streaming downloads + .meta.json sidecars
http_utils.py    UA, timeouts, rate limit, retries
providers/       one module per source
```

> Note: written to run on Python 3.9+ (`from __future__ import annotations`);
> the original brief targeted 3.11+, but this machine ships 3.9.
