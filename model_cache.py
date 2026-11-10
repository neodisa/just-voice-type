"""Есть ли модель Hugging Face в локальном кэше (без сети и без huggingface_hub).

Нужно, чтобы строка статуса различала «Загружаю модель…» (веса уже на
диске) и «Скачиваю модель…» (первая загрузка, гигабайты из сети).
"""
from __future__ import annotations

import os
from typing import Optional

WEIGHT_EXT = (".safetensors", ".npz", ".bin", ".gguf")


def hub_cache_dir() -> str:
    if os.environ.get("HF_HUB_CACHE"):
        return os.environ["HF_HUB_CACHE"]
    home = os.environ.get("HF_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface"
    )
    return os.path.join(home, "hub")


def repo_dir(repo: str, cache: Optional[str] = None) -> str:
    return os.path.join(cache or hub_cache_dir(), "models--" + repo.replace("/", "--"))


def is_cached(repo: str, cache: Optional[str] = None) -> bool:
    """True, если веса модели уже лежат в кэше и докачка не идёт.
    Имена не из хаба (CPU-движок «large-v3», локальный путь) — True."""
    if "/" not in repo or os.path.isabs(repo) or os.path.exists(repo):
        return True
    d = repo_dir(repo, cache)
    blobs = os.path.join(d, "blobs")
    if os.path.isdir(blobs) and any(n.endswith(".incomplete") for n in os.listdir(blobs)):
        return False
    snaps = os.path.join(d, "snapshots")
    if not os.path.isdir(snaps):
        return False
    for _root, _dirs, files in os.walk(snaps):
        if any(f.endswith(WEIGHT_EXT) for f in files):
            return True
    return False
