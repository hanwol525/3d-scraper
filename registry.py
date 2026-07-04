"""Assemble the provider registry. Order = display order in the picker:
zero-config sources first, then keyed, then gated, then honest stubs."""
from __future__ import annotations

from config import Settings
from providers.base import ModelProvider
from providers.cults3d import Cults3dProvider
from providers.myminifactory import MyMiniFactoryProvider
from providers.nasa import NasaProvider
from providers.smithsonian import Smithsonian3dProvider, SmithsonianOpenAccessProvider
from providers.thingiverse import ThingiverseProvider
from providers.scaffolds import (
    GrabCadProvider,
    Nih3dProvider,
    ThangsProvider,
    YeggiProvider,
    YouMagineProvider,
)


def build_registry(settings: Settings) -> dict:
    providers: list[ModelProvider] = [
        Smithsonian3dProvider(settings),
        NasaProvider(settings),
        ThingiverseProvider(settings),
        SmithsonianOpenAccessProvider(settings),
        MyMiniFactoryProvider(settings),
        Cults3dProvider(settings),
        YeggiProvider(settings),
        GrabCadProvider(settings),
        YouMagineProvider(settings),
        ThangsProvider(settings),
        Nih3dProvider(settings),
    ]
    return {p.name: p for p in providers}
