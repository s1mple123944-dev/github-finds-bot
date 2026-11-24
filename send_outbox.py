#!/usr/bin/env python3
"""
Отправляет владельцу в личку всё, что лежит в outbox/:
  outbox/<имя>.mp4  — видео
  outbox/<имя>.txt  — (необязательно) текст, придёт ответом на видео
После отправки файлы удаляются из outbox/.
"""
import json
import os
import sys

import bot

BASE = os.path.dirname(os.path.abspath(__file__))
OUTBOX = os.path.join(BASE, "outbox")


def main():
    cfg = bot.load_config()
    owner = os.environ.get("TG_OWNER_ID") or open(os.path.join(BASE, "state", "owner_chat_id.txt")).read().strip()
    for name in sorted(os.listdir(OUTBOX)):
        if not name.endswith(".mp4"):
            continue
        path = os.path.join(OUTBOX, name)
        with open(path, "rb") as f:
            data = f.read()
        msg = bot.tg(cfg, "sendVideo", {"chat_id": owner, "width": 1080, "height": 1920,
                                        "supports_streaming": "true",
                                        "caption": "🎬 Ролик для TikTok / Reels. Описание — ответом ниже."},
                     files={"video": (name, data, "video/mp4")}, timeout=300)
        txt = path[:-4] + ".txt"
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                bot.tg(cfg, "sendMessage", {"chat_id": owner, "text": f.read(),
                                            "reply_parameters": json.dumps({"message_id": msg["message_id"]})})
            os.remove(txt)
        os.remove(path)
        bot.log("Отправлено:", name)


if __name__ == "__main__":
    main()
