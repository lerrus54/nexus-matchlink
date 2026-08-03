"""Создание GitHub-релиза с готовым .exe.

Использование:
    python tools/release_github.py [--version 1.6.0] [--notes "что нового"]
                                   [--file dist\\NexusMatchlink.exe] [--prerelease]

Зависит от установленного GitHub CLI (gh) и авторизации (gh auth login).
Релиз и загруженный файл появляются на github.com/lerrus54/nexus-matchlink
и автоматически подхватываются встроенной проверкой обновлений приложения.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from core.version import APP_VERSION  # noqa: E402

DEFAULT_REPO = "lerrus54/nexus-matchlink"
GH_PATHS = [
    r"C:\Program Files\GitHub CLI\gh.exe",
    r"C:\Program Files (x86)\GitHub CLI\gh.exe",
    "gh",
]


def find_gh() -> str:
    for candidate in GH_PATHS:
        if shutil.which(candidate) or Path(candidate).is_file():
            return candidate
    raise RuntimeError(
        "GitHub CLI (gh) не найден. Установите его и выполните: gh auth login"
    )


def run(gh: str, args: list[str]) -> None:
    result = subprocess.run(
        [gh, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Создание GitHub-релиза Nexus Matchlink")
    parser.add_argument("--version", default=APP_VERSION, help="версия, например 1.6.0")
    parser.add_argument("--notes", default="", help="текст «что нового» (или путь к .md)")
    parser.add_argument(
        "--file",
        type=Path,
        default=PROJECT_ROOT / "dist" / "NexusMatchlink.exe",
        help="путь к .exe для загрузки",
    )
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--prerelease", action="store_true", help="пометить как pre-release")
    args = parser.parse_args(argv)

    version = args.version.strip().lstrip("v")
    tag = f"v{version}"

    if not args.file.is_file():
        print(f"[ERROR] Файл не найден: {args.file}")
        return 1

    notes = args.notes.strip()
    if notes.lower().endswith(".md") and Path(notes).is_file():
        notes = Path(notes).read_text(encoding="utf-8")
    if not notes:
        notes = f"NexusMatchlink v{version}"

    gh = find_gh()

    print(f"==> Создаю релиз {tag} в {args.repo}...")
    create_args = [
        "release", "create", tag,
        "--repo", args.repo,
        "--title", f"NexusMatchlink {tag}",
        "--notes", notes,
    ]
    if args.prerelease:
        create_args.append("--prerelease")
    run(gh, create_args)

    print(f"==> Загружаю {args.file.name}...")
    run(gh, ["release", "upload", tag, str(args.file), "--repo", args.repo])

    print(f"OK: https://github.com/{args.repo}/releases/tag/{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
