"""Providers that CANNOT be implemented against an official API as of
2026-07-03. Each finding below was verified against live docs/probes — these
are honest stubs, not guessed endpoints. Details in README §Provider status."""
from __future__ import annotations

from models import ModelResult
from providers.base import ModelProvider


class _Scaffold(ModelProvider):
    implemented = False
    unimplemented_label = "no usable API — see README"
    todo = "TODO: no verified API — see README §Provider status"

    def search(self, query: str, file_type: str | None, limit: int) -> list[ModelResult]:
        raise NotImplementedError(self.todo)


class YeggiProvider(_Scaffold):
    name = "Yeggi"
    notes = (
        "No API exists (verified 2026-07-03) — public, partner, or paid. The site "
        "bot-challenges scripted clients. Yeggi is a meta-search that links out to "
        "other hosts; search it in a browser: https://www.yeggi.com"
    )


class GrabCadProvider(_Scaffold):
    name = "GrabCAD"
    notes = (
        "No public API for the model library (verified 2026-07-03). The Workbench "
        "API was shut down June 2023; current SDKs cover Stratasys printers only, "
        "and the site's CDN blocks non-browser clients."
    )


class YouMagineProvider(_Scaffold):
    name = "YouMagine"
    notes = (
        "API defunct (verified 2026-07-03): api.youmagine.com no longer resolves in "
        "DNS. YouMagine was acquired by MyMiniFactory in 2024 and the new site "
        "publishes no API."
    )


class ThangsProvider(_Scaffold):
    name = "Thangs"
    notes = (
        "No public API (verified 2026-07-03). The site's internal search endpoint is "
        "bot-protected and Thangs' content policy prohibits automated scraping/bulk "
        "download; the Physna enterprise API only covers your own uploads."
    )


class Nih3dProvider(_Scaffold):
    name = "NIH 3D"
    notes = (
        "The old 3D Print Exchange public API was retired (developer docs now 404; "
        "verified 2026-07-03). The rebuilt 3d.nih.gov renders search server-side and "
        "exposes no JSON search endpoint — only per-file binary routes."
    )
