"""Проверка новых версий через GitHub Releases.

``latest_release()`` читает последний публичный релиз репозитория через
GitHub API. Любая сетевая/API ошибка возвращает None — приложение никогда
не падает и не тормозит из-за отсутствия интернета. Версии сравниваются
по кортежу (major, minor, patch).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

REPO = "lerrus54/nexus-matchlink"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
REQUEST_TIMEOUT = 10

_TAG_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class UpdateInfo:
    """Сведения о доступном обновлении."""

    version: str
    notes: str
    url: str

    @property
    def tag(self) -> str:
        return self.version if self.version.startswith("v") else f"v{self.version}"


def parse_version(value: str) -> Optional[tuple[int, int, int]]:
    """Разбирает строку версии в кортеж (major, minor, patch).

    Понимает "1.5.0", "v1.5.0", "release-1.5.0-beta". None — если не похоже
    на версию.
    """
    match = _TAG_RE.search(value)
    if match is None:
        return None
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def latest_release() -> Optional[UpdateInfo]:
    """Возвращает последний релиз репозитория или None при любой ошибке."""
    try:
        response = requests.get(
            RELEASES_URL,
            headers={"Accept": "application/vnd.github+json"},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 404:
            logger.debug("Релизов в %s ещё нет", REPO)
            return None
        response.raise_for_status()
        data = response.json()
        tag = str(data.get("tag_name") or "")
        version = tag.lstrip("v") or "0.0.0"
        return UpdateInfo(
            version=version,
            notes=str(data.get("body") or "").strip(),
            url=str(data.get("html_url") or f"https://github.com/{REPO}/releases"),
        )
    except requests.RequestException as exc:
        logger.debug("Не удалось проверить обновления: %s", exc)
        return None
    except ValueError as exc:
        logger.debug("Некорректный ответ GitHub API: %s", exc)
        return None


def check_for_update(local_version: str) -> Optional[UpdateInfo]:
    """Сравнивает локальную версию с последним релизом.

    Возвращает UpdateInfo, если на GitHub есть более новая версия, иначе
    None (включая случай, когда релиз недоступен или версии равны).
    """
    local = parse_version(local_version)
    release = latest_release()
    if release is None:
        return None
    remote = parse_version(release.version)
    if local is None or remote is None or remote <= local:
        return None
    return release


__all__ = ["UpdateInfo", "check_for_update", "latest_release", "parse_version"]
