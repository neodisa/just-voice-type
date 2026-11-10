"""Каталог моделей распознавания, которые предлагает окно настроек.

Размеры — фактический объём весов в кэше Hugging Face (ГиБ), описания —
в i18n (settings.model.<slug>.desc). Модель не из каталога (передана
флагом --model) показывается под своим именем из id.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

GIB = 1024 ** 3


@dataclass(frozen=True)
class CatalogModel:
    id: str
    slug: str
    name: str
    size_gb: float
    default: bool = False

    @property
    def size_bytes(self) -> int:
        return int(self.size_gb * GIB)


MODELS = (
    CatalogModel("mlx-community/parakeet-tdt-0.6b-v3", "parakeet", "Parakeet v3", 2.3, default=True),
    CatalogModel("mlx-community/whisper-large-v3-mlx", "large", "Whisper Large v3", 2.9),
    CatalogModel("mlx-community/whisper-large-v3-turbo", "turbo", "Whisper Turbo", 1.5),
    CatalogModel("mlx-community/whisper-medium-mlx", "medium", "Whisper Medium", 1.5),
    CatalogModel("mlx-community/whisper-small-mlx", "small", "Whisper Small", 0.5),
)

# LLM для режимов «Чистовой» / «Для ИИ» (polish.POLISH_MODEL), ГиБ
POLISH_SIZE_GB = 0.8


def get(model_id: str) -> "Optional[CatalogModel]":
    for m in MODELS:
        if m.id == model_id:
            return m
    return None


def display_name(model_id: str) -> str:
    m = get(model_id)
    return m.name if m else (model_id or "").rstrip("/").split("/")[-1]


def is_parakeet(model_id: str) -> bool:
    return "parakeet" in (model_id or "").lower()
