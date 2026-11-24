#!/usr/bin/env python3
"""
GitHub Finds bot.

Берёт готовые посты (JSON) из папки queue/, отправляет их в Telegram
с видео / гифкой / картинкой и переносит в sent/ (или failed/ при ошибке).

Посты в queue/ кладёт Claude (скилл github-finds). Токен бота хранится
только у тебя: в config.json или в переменной окружения TG_BOT_TOKEN.

Запуск:
    python bot.py            — работать постоянно, проверять очередь раз в N секунд
    python bot.py --once     — отправить всё, что есть в очереди, и выйти
    python bot.py --whoami   — показать chat_id тех, кто писал боту (для настройки)

Никаких внешних библиотек не нужно — только стандартный Python 3.8+.
"""
import html
import json
import os
import re
import shutil
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(BASE, "queue")
SENT = os.path.join(BASE, "sent")
FAILED = os.path.join(BASE, "failed")
CONFIG_PATH = os.path.join(BASE, "config.json")
CHAT_FILE = os.path.join(BASE, "state", "chat_id.txt")

UA = "github-finds-bot/1.0"
MAX_UPLOAD = 50 * 1024 * 1024      # лимит Bot API на загрузку файла
CAPTION_LIMIT = 1024               # лимит подписи к медиа
TEXT_LIMIT = 4096                  # лимит обычного сообщения

METHODS = {
    "video": ("sendVideo", "video"),
    "animation": ("sendAnimation", "animation"),
    "photo": ("sendPhoto", "photo"),
}

try:  # чтобы русский текст нормально печатался в консоли Windows
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def log(*args):
    print(time.strftime("[%H:%M:%S]"), *args, flush=True)


# ---------------------------------------------------------------- config

def load_config():
    cfg = {"bot_token": "", "chat_id": "", "shorten_links": False,
           "poll_seconds": 60, "disable_notification": False}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    cfg["bot_token"] = os.environ.get("TG_BOT_TOKEN", cfg["bot_token"]).strip()
    cfg["chat_id"] = str(os.environ.get("TG_CHAT_ID", cfg["chat_id"])).strip()
    if not cfg["bot_token"] or "ВСТАВЬ" in cfg["bot_token"]:
        if not sys.stdin or not sys.stdin.isatty():
            sys.exit("Нет токена бота. Впиши его в config.json (bot_token).")
        print("Первый запуск. Создай бота у @BotFather (/newbot) и вставь сюда его токен.")
        cfg["bot_token"] = input("Токен: ").strip()
        save_config(cfg)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def detect_chat_once(cfg):
    """Без консоли (GitHub Actions): берёт chat_id из последнего /start и
    сохраняет его в state/chat_id.txt (chat_id — не секрет, токен — секрет)."""
    chat = None
    for u in tg(cfg, "getUpdates", {"timeout": 0}):
        m = u.get("message") or {}
        if m.get("chat", {}).get("type") == "private":
            chat = str(m["chat"]["id"])
    if not chat:
        return False
    cfg["chat_id"] = chat
    os.makedirs(os.path.dirname(CHAT_FILE), exist_ok=True)
    with open(CHAT_FILE, "w", encoding="utf-8") as f:
        f.write(chat)
    tg(cfg, "sendMessage", {"chat_id": chat,
       "text": "✅ Подключено. Сюда будут приходить находки с GitHub."})
    log(f"chat_id {chat} сохранён в state/chat_id.txt")
    return True


def check_channel(cfg):
    """Если бота сделали админом канала — дальше публикуем в канал.
    Канал запоминается в state/chat_id.txt, тебе в личку приходит уведомление."""
    found = None
    for u in tg(cfg, "getUpdates", {"timeout": 0, "allowed_updates": '["my_chat_member","message"]'}):
        m = u.get("my_chat_member")
        if not m or m["chat"].get("type") != "channel":
            continue
        status = m["new_chat_member"]["status"]
        can_post = m["new_chat_member"].get("can_post_messages", status == "creator")
        if status in ("administrator", "creator") and can_post:
            found = m["chat"]
        elif str(m["chat"]["id"]) == str(found and found["id"]):
            found = None
    if not found or str(found["id"]) == cfg["chat_id"]:
        return
    old = cfg["chat_id"]
    cfg["chat_id"] = str(found["id"])
    os.makedirs(os.path.dirname(CHAT_FILE), exist_ok=True)
    with open(CHAT_FILE, "w", encoding="utf-8") as f:
        f.write(cfg["chat_id"])
    title = found.get("title", "канал")
    log(f"Нашёл канал «{title}» ({cfg['chat_id']}) — публикую туда")
    if old:
        try:
            tg(cfg, "sendMessage", {"chat_id": old,
               "text": f"✅ Я админ в канале «{title}». Дальше публикую находки туда."})
        except Exception:
            pass


def wait_for_chat(cfg):
    """Ждёт /start от пользователя и запоминает его chat_id."""
    me = tg(cfg, "getMe", {})
    print(f"Теперь открой в Telegram @{me['username']} и нажми «Start» (/start). Жду…")
    offset = None
    while True:
        fields = {"timeout": 50}
        if offset:
            fields["offset"] = offset
        for u in tg(cfg, "getUpdates", fields, timeout=70):
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            if m.get("chat", {}).get("type") == "private":
                cfg["chat_id"] = str(m["chat"]["id"])
                save_config(cfg)
                tg(cfg, "getUpdates", {"offset": offset, "timeout": 0})
                tg(cfg, "sendMessage", {"chat_id": cfg["chat_id"],
                   "text": "✅ Подключено. Сюда будут приходить находки с GitHub."})
                log(f"chat_id {cfg['chat_id']} сохранён в config.json")
                return


# ---------------------------------------------------------------- telegram

class TgError(Exception):
    pass


def _multipart(fields, files):
    boundary = "----ghfinds" + uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        if v is None:
            continue
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
        out += str(v).encode("utf-8") + b"\r\n"
    for k, (fname, data, ctype) in files.items():
        out += f"--{boundary}\r\n".encode()
        out += (f'Content-Disposition: form-data; name="{k}"; '
                f'filename="{fname}"\r\n').encode()
        out += f"Content-Type: {ctype}\r\n\r\n".encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def tg(cfg, method, fields, files=None, timeout=120):
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/{method}"
    body, ctype = _multipart(fields, files or {})
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8"))
        except Exception:
            raise TgError(f"{method}: HTTP {e.code}")
    except urllib.error.URLError as e:
        raise TgError(f"{method}: нет связи с Telegram ({e.reason})")
    if not data.get("ok"):
        raise TgError(f"{method}: {data.get('description')}")
    return data["result"]


# ---------------------------------------------------------------- helpers

def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        ctype = r.headers.get("Content-Type", "application/octet-stream").split(";")[0]
        data = r.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise TgError("файл больше 50 МБ")
    name = os.path.basename(urllib.parse.urlparse(url).path) or "media"
    if "." not in name:
        ext = {"video/mp4": ".mp4", "image/gif": ".gif", "image/png": ".png",
               "image/jpeg": ".jpg", "image/webp": ".webp"}.get(ctype, "")
        name += ext
    return name, data, ctype


def shorten(url):
    """Короткая ссылка через clck.ru (Яндекс). Если не вышло — исходная."""
    try:
        q = "https://clck.ru/--?url=" + urllib.parse.quote(url, safe="")
        req = urllib.request.Request(q, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            short = r.read().decode().strip()
        if short.startswith("https://clck.ru/"):
            return short
    except Exception as e:
        log("  не удалось сократить ссылку:", e)
    return url


def visible_len(text_html):
    return len(html.unescape(re.sub(r"<[^>]+>", "", text_html)))


def render(post, link):
    # Скрытая ссылка: в тексте видно «owner/repo», а ведёт она на GitHub
    label = post.get("link_text") or post.get("repo") or link
    a = f'<a href="{html.escape(link, quote=True)}">{html.escape(label)}</a>'
    text = post.get("text", "")
    if "{link}" in text:
        return text.replace("{link}", a)
    return f"{text}\n\n🔗 {a}"


# ---------------------------------------------------------------- sending

def send_media(cfg, item, caption):
    kind = item.get("type", "photo")
    method, field = METHODS.get(kind, METHODS["photo"])
    base = {"chat_id": cfg["chat_id"], "parse_mode": "HTML",
            "caption": caption,
            "disable_notification": str(cfg["disable_notification"]).lower()}
    if kind in ("video", "animation"):
        base["supports_streaming"] = "true"
    # 1) пусть Telegram сам скачает по ссылке
    try:
        return tg(cfg, method, {**base, field: item["url"]})
    except TgError as e:
        log(f"  {kind} по ссылке не прошёл ({e}), качаю сам…")
    # 2) скачиваем сами и загружаем файлом
    name, data, ctype = download(item["url"])
    return tg(cfg, method, base, files={field: (name, data, ctype)}, timeout=300)


def send_post(cfg, post):
    link = post["url"]
    if cfg.get("shorten_links", False):
        link = shorten(link)
    full = render(post, link)

    caption, tail = full, None
    if visible_len(full) > CAPTION_LIMIT:
        # длинный текст: под медиа — заголовок и ссылка, полный текст отдельным сообщением
        title = html.escape(post.get("title", post.get("repo", "")))
        caption = f"<b>{title}</b>\n\n🔗 " + render({"text": "{link}", "repo": post.get("repo")}, link)
        tail = full

    candidates = list(post.get("media", []))
    if post.get("fallback_image"):
        candidates.append({"type": "photo", "url": post["fallback_image"]})

    msg = None
    for item in candidates:
        try:
            msg = send_media(cfg, item, caption)
            log(f"  отправлено: {item.get('type')} {item['url']}")
            break
        except Exception as e:
            log(f"  медиа не подошло: {item.get('url')} — {e}")

    if msg is None:  # ни одно медиа не прошло — шлём текст с превью ссылки
        tail = full
    if tail:
        if visible_len(tail) > TEXT_LIMIT:
            tail = tail[:TEXT_LIMIT - 10] + "…"
        fields = {"chat_id": cfg["chat_id"], "text": tail, "parse_mode": "HTML"}
        if msg:
            fields["reply_parameters"] = json.dumps({"message_id": msg["message_id"]})
            fields["link_preview_options"] = json.dumps({"is_disabled": True})
        msg2 = tg(cfg, "sendMessage", fields)
        msg = msg or msg2
    return msg


def process_queue(cfg):
    for d in (QUEUE, SENT, FAILED):
        os.makedirs(d, exist_ok=True)
    files = sorted(f for f in os.listdir(QUEUE) if f.endswith(".json"))
    for fname in files:
        path = os.path.join(QUEUE, fname)
        log("Пост:", fname)
        try:
            with open(path, encoding="utf-8") as f:
                post = json.load(f)
            msg = send_post(cfg, post)
            post["sent_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            post["message_id"] = msg.get("message_id")
            with open(os.path.join(SENT, fname), "w", encoding="utf-8") as f:
                json.dump(post, f, ensure_ascii=False, indent=2)
            os.remove(path)
            log("  ✓ готово")
        except Exception as e:
            log("  ✗ ошибка:", e)
            with open(os.path.join(FAILED, fname + ".error.txt"), "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
            shutil.move(path, os.path.join(FAILED, fname))
        time.sleep(2)


def whoami(cfg):
    updates = tg(cfg, "getUpdates", {})
    seen = {}
    for u in updates:
        m = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        chat = m.get("chat")
        if chat:
            seen[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name")
    if not seen:
        print("Пусто. Напиши боту /start (или добавь его админом в канал и опубликуй там пост), "
              "потом запусти снова.")
    for cid, name in seen.items():
        print(f"chat_id = {cid}   ({name})")


def main():
    cfg = load_config()
    if "--whoami" in sys.argv:
        return whoami(cfg)
    if not cfg["chat_id"] and os.path.exists(CHAT_FILE):
        cfg["chat_id"] = open(CHAT_FILE, encoding="utf-8").read().strip()
    if not cfg["chat_id"]:
        if sys.stdin and sys.stdin.isatty():
            wait_for_chat(cfg)
        elif not detect_chat_once(cfg):
            sys.exit("chat_id не найден: открой своего бота в Telegram, нажми «Start» "
                     "и перезапусти (на GitHub: Actions → Send posts → Run workflow).")
    if not os.environ.get("TG_CHAT_ID"):
        try:
            check_channel(cfg)
        except Exception as e:
            log("Проверка канала не удалась:", e)
    if "--once" in sys.argv:
        return process_queue(cfg)
    log(f"Бот запущен. Слежу за {QUEUE} каждые {cfg['poll_seconds']} с. Ctrl+C — выход.")
    while True:
        try:
            process_queue(cfg)
        except Exception as e:
            log("Ошибка цикла:", e)
        time.sleep(int(cfg["poll_seconds"]))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
