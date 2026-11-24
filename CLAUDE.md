# GitHub Finds bot

Telegram-канал «GitHub Finder»: каждый день 3 полезные находки с GitHub + ролики для TikTok / Reels.

- `bot.py` — отправка постов из `queue/` в Telegram (запускается GitHub Actions на push, `.github/workflows/send.yml`). Удаление постов — через `delete/`.
- `reel.py` — быстрый ролик без голоса (Pillow + ffmpeg), каждый вечер в 22:13 по Минску (`.github/workflows/reel.yml`); `--send-file` присылает любой готовый ролик владельцу.
- Ролики с голосом и точными субтитрами — в Remotion: скилл `.claude/skills/github-finder-reel` (использует официальные скиллы `remotion-best-practices`).
- `sent/` — история постов (не повторять находки), `state/` — chat_id канала и владельца.
- Токен бота — только в секретах GitHub (`TG_BOT_TOKEN`) или локальном `config.json` (в .gitignore). Никогда не коммитить и не выводить его.

Правила отбора находок: телефон — Android **и** iOS; ПК — Windows **и** macOS; связки ПК↔телефон приветствуются; AI-инструменты — любая платформа. Медиа меньше 480×270 не прикреплять.
