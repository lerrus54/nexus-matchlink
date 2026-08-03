"""Публикация обновления в Telegram-канал Nexus Matchlink.

Использование:
    python tools/publish_update.py <файл.exe> --version v1.4.1 [--text "что нового"] [--chat @nexus_matchlink]

Пост уходит в канал как документ с подписью. Токен бота берётся
из config/settings.json (тот же бот, что уведомляет о матчах).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import load_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_CHANNEL = "@nexus_matchlink"


def channel_chat_id(token: str, username: str) -> int:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/getChat",
        data={"chat_id": username},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"getChat: {data.get('description')}")
    return int(data["result"]["id"])


def publish(
    token: str,
    chat_id: int,
    file_path: Path,
    caption: str,
) -> int:
    with open(file_path, "rb") as handle:
        files = {
            "document": (file_path.name, handle, "application/octet-stream")
        }
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption},
            files=files,
            timeout=300,
        )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"sendDocument: {data.get('description')}")
    return int(data["result"]["message_id"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Публикация обновления в канал Nexus Matchlink")
    parser.add_argument("file", type=Path, help="путь к .exe/архиву для публикации")
    parser.add_argument("--version", default="", help="версия, например v1.4.1")
    parser.add_argument("--text", default="", help="что нового (строка)")
    parser.add_argument("--chat", default=DEFAULT_CHANNEL, help="канал или id")
    args = parser.parse_args(argv)

    if not args.file.is_file():
        logger.error("Файл не найден: %s", args.file)
        return 1

    config = load_config()
    token = config.telegram.bot_token
    if not token:
        logger.error("bot_token пуст — заполните config/settings.json")
        return 1

    lines = ["NexusMatchlink " + args.version.strip()] if args.version.strip() else []
    if args.text.strip():
        lines.append(args.text.strip())
    caption = "\n".join(lines).strip()
    if not caption:
        caption = args.file.name

    chat_id = int(args.chat) if args.chat.lstrip("+-").isdigit() else channel_chat_id(token, args.chat)
    message_id = publish(token, chat_id, args.file, caption)
    logger.info("Опубликовано в %s (msg_id=%s): %s", args.chat, message_id, caption)
    return 0


if __name__ == "__main__":
    sys.exit(main())
