"""Стейджинг чистого конфига для сборки .exe.

Берёт ``config/settings.template.json`` (публичный, без токена) и
подставляет реальный ``bot_token`` из локального ``config/settings.json``
(не хранится в git). Результат — ``build_resources/config/settings.json``,
который PyInstaller вкладывает в .exe.

Так токен бота не попадает в публичный репозиторий, а сборка продолжает
работать: локальный конфиг есть у разработчика, у конечных пользователей
приложение создаёт конфиг рядом с .exe само.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    template_path = PROJECT_ROOT / "config" / "settings.template.json"
    local_path = PROJECT_ROOT / "config" / "settings.json"
    out_path = PROJECT_ROOT / "build_resources" / "config" / "settings.json"

    template = json.loads(template_path.read_text(encoding="utf-8-sig"))

    token = ""
    if local_path.is_file():
        try:
            local = json.loads(local_path.read_text(encoding="utf-8-sig"))
            token = str(local.get("telegram", {}).get("bot_token", ""))
        except (OSError, ValueError) as exc:
            print(f"[stage_config] warning: не прочитан {local_path}: {exc}")

    telegram = template.setdefault("telegram", {})
    telegram["bot_token"] = token

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[stage_config] написан {out_path} (bot_token={'задан' if token else 'пуст'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
