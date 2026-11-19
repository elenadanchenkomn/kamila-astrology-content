"""Публикатор Камилы: Instagram и Facebook напрямую через Meta Graph API, без Metricool.

Что публикует:
  * недельные очереди captions/<неделя>/queue.json (Reels, карусели, посты, истории),
    если в файле стоит "publisher": "github";
  * посты, которые бот передаёт после публикации в Telegram: captions/auto/ГГГГ-ММ/ГГГГ-ММ-ДД.json.

Запускается из .github/workflows/publish.yml каждые 15 минут и при новых файлах в captions/.
Что уже опубликовано — automation/published.json (коммитит сам workflow).

Секреты (Settings → Secrets and variables → Actions):
  META_PAGE_TOKEN — бессрочный токен страницы или пользователя с доступом к странице (обязательный);
  FB_PAGE_ID, IG_USER_ID — по желанию, иначе определяются по токену;
  TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID — по желанию, для сообщений об ошибках.
Настройка — automation/PUBLISHING.md.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "automation" / "publisher.json").read_text(encoding="utf-8"))
STATE_PATH = ROOT / "automation" / "published.json"
JPG_DIR = ROOT / "automation" / "jpg"
TZ = ZoneInfo(CFG.get("timezone", "Europe/Moscow"))
GV = CFG.get("graph_version", "v23.0")
G = f"https://graph.facebook.com/{GV}"
GV_VIDEO = f"https://graph-video.facebook.com/{GV}"
TOKEN = os.environ.get("META_PAGE_TOKEN", "").strip()
REPO = os.environ.get("GITHUB_REPOSITORY", CFG.get("repo", "elenadanchenkomn/kamila-astrology-content"))
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
ONLY = os.environ.get("ONLY_KEY", "").strip()   # опубликовать одну задачу сейчас (для проверки)


# ---------------- вспомогательное ----------------

class MetaError(Exception):
    pass


def api(method: str, url: str, **kw) -> dict:
    params = kw.pop("params", {}) or {}
    params.setdefault("access_token", TOKEN)
    for attempt in range(3):
        try:
            r = requests.request(method, url, params=params, timeout=kw.pop("timeout", 120), **kw)
        except requests.RequestException as e:
            if attempt == 2:
                raise MetaError(f"сеть: {e}") from e
            time.sleep(5)
            continue
        try:
            data = r.json()
        except ValueError:
            data = {"error": {"message": r.text[:300]}}
        if r.status_code >= 500 and attempt < 2:
            time.sleep(5)
            continue
        if "error" in data:
            e = data["error"]
            raise MetaError(f"{e.get('message')} (code {e.get('code')}, subcode {e.get('error_subcode')})")
        return data
    raise MetaError("нет ответа")


def notify(text: str):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("ADMIN_CHAT_ID")
    if not (tok and chat):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": text[:3900], "disable_web_page_preview": "true"}, timeout=20)
    except requests.RequestException:
        pass


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"published": {}, "failed": {}}


def save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


# ---------------- очередь ----------------

def media_dir_for(queue_file: Path, data: dict) -> Path:
    """captions/2026-11-23-week/queue.json → images/2026/11/week-23/ (как сейчас раскладываются файлы)."""
    if data.get("media_dir"):
        return ROOT / data["media_dir"]
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})-week", queue_file.parent.name)
    if m:
        return ROOT / "images" / m.group(1) / m.group(2) / f"week-{m.group(3)}"
    return ROOT


def load_jobs() -> list:
    jobs = []
    files = sorted(ROOT.glob("captions/*/queue.json")) + sorted(ROOT.glob("captions/auto/*/*.json"))
    for qf in files:
        try:
            data = json.loads(qf.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"⚠️ {qf.relative_to(ROOT)}: не читается ({e})")
            continue
        if data.get("publisher") != "github":
            continue
        base = media_dir_for(qf, data)
        for j in data.get("jobs", []):
            if not j.get("key") or not j.get("date"):
                continue
            j = dict(j)
            j["id"] = f"{qf.parent.name}/{qf.stem}/{j['key']}" if "auto" in qf.parts else f"{qf.parent.name}/{j['key']}"
            j["when"] = datetime.fromisoformat(j["date"]).astimezone(TZ)
            j["files"] = [(ROOT / m) if "/" in m else (base / m) for m in j.get("media", [])]
            jobs.append(j)
    return sorted(jobs, key=lambda x: x["when"])


# ---------------- картинки для Instagram (только JPEG по ссылке) ----------------

def ensure_jpegs(jobs: list) -> bool:
    """Instagram принимает картинки только JPEG и только по публичной ссылке. Делаем JPEG-копии
    в automation/jpg/ и коммитим их до публикации. Возвращает True, если появились новые файлы."""
    from PIL import Image

    created = False
    for j in jobs:
        if j.get("network") != "instagram":
            continue
        for f in j["files"]:
            if f.suffix.lower() not in (".png", ".webp"):
                continue
            out = JPG_DIR / f.relative_to(ROOT).with_suffix(".jpg")
            if out.exists() or not f.exists():
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            img = Image.open(f).convert("RGB")
            img.save(out, "JPEG", quality=92, optimize=True)
            created = True
            print(f"🖼 JPEG: {out.relative_to(ROOT)}")
    return created


def public_url(f: Path, sha: str) -> str:
    if f.suffix.lower() in (".png", ".webp"):
        f = JPG_DIR / f.relative_to(ROOT).with_suffix(".jpg")
    rel = f.relative_to(ROOT).as_posix()
    return f"https://raw.githubusercontent.com/{REPO}/{sha}/{rel}"


# ---------------- Instagram ----------------

def ig_wait(container: str, limit_s: int = 600):
    start = time.time()
    while True:
        st = api("GET", f"{G}/{container}", params={"fields": "status_code,status"})
        code = st.get("status_code")
        if code in ("FINISHED", "PUBLISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise MetaError(f"контейнер {container}: {code} {st.get('status', '')}")
        if time.time() - start > limit_s:
            raise MetaError(f"контейнер {container}: не обработан за {limit_s} с")
        time.sleep(8)


def ig_video_container(ig: str, f: Path, fields: dict) -> str:
    """Видео (Reels, история) загружаем файлом через resumable upload — ссылка на видео не нужна."""
    c = api("POST", f"{G}/{ig}/media", data={**fields, "upload_type": "resumable"})
    uri = c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{GV}/{c['id']}"
    body = f.read_bytes()
    r = requests.post(uri, data=body, timeout=600, headers={
        "Authorization": f"OAuth {TOKEN}", "offset": "0", "file_size": str(len(body))})
    if r.status_code >= 300:
        raise MetaError(f"загрузка видео: {r.status_code} {r.text[:200]}")
    return c["id"]


def publish_instagram(j: dict, ig: str, sha: str) -> str:
    t, files, caption = j["type"].upper(), j["files"], j.get("text", "")
    imgs = [f for f in files if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    vids = [f for f in files if f.suffix.lower() in (".mp4", ".mov")]
    if t == "STORY":
        if vids:
            cid = ig_video_container(ig, vids[0], {"media_type": "STORIES"})
        else:
            cid = api("POST", f"{G}/{ig}/media", data={"media_type": "STORIES",
                                                        "image_url": public_url(imgs[0], sha)})["id"]
    elif t == "REEL":
        cid = ig_video_container(ig, vids[0], {"media_type": "REELS", "caption": caption, "share_to_feed": "true"})
    elif len(imgs) > 1:
        kids = [api("POST", f"{G}/{ig}/media", data={"image_url": public_url(f, sha), "is_carousel_item": "true"})["id"]
                for f in imgs[:10]]
        for k in kids:
            ig_wait(k, 120)
        cid = api("POST", f"{G}/{ig}/media", data={"media_type": "CAROUSEL", "children": ",".join(kids),
                                                    "caption": caption})["id"]
    elif imgs:
        cid = api("POST", f"{G}/{ig}/media", data={"image_url": public_url(imgs[0], sha), "caption": caption})["id"]
    else:
        raise MetaError("в Instagram нельзя опубликовать пост без картинки или видео")
    ig_wait(cid)
    media_id = api("POST", f"{G}/{ig}/media_publish", data={"creation_id": cid})["id"]
    if j.get("firstCommentText") and t != "STORY":
        try:
            api("POST", f"{G}/{media_id}/comments", data={"message": j["firstCommentText"]})
        except MetaError as e:
            print(f"⚠️ первый комментарий не добавлен: {e}")
    return media_id


# ---------------- Facebook ----------------

def fb_photo(page: str, f: Path, **data) -> dict:
    with f.open("rb") as fh:
        return api("POST", f"{G}/{page}/photos", data=data, files={"source": (f.name, fh)})


def publish_facebook(j: dict, page: str) -> str:
    t, files, text = j["type"].upper(), j["files"], j.get("text", "")
    imgs = [f for f in files if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    vids = [f for f in files if f.suffix.lower() in (".mp4", ".mov")]
    if t == "STORY":
        if not imgs:
            raise MetaError("видео-истории в Facebook пока не поддержаны — пропустите или опубликуйте вручную")
        photo = fb_photo(page, imgs[0], published="false")
        return api("POST", f"{G}/{page}/photo_stories", data={"photo_id": photo["id"]}).get("post_id", photo["id"])
    if vids:
        with vids[0].open("rb") as fh:
            post_id = api("POST", f"{GV_VIDEO}/{page}/videos", data={"description": text},
                          files={"source": (vids[0].name, fh)}, timeout=600)["id"]
    elif len(imgs) > 1:
        ids = [fb_photo(page, f, published="false")["id"] for f in imgs[:10]]
        post_id = api("POST", f"{G}/{page}/feed", data={
            "message": text, "attached_media": json.dumps([{"media_fbid": i} for i in ids])})["id"]
    elif imgs:
        r = fb_photo(page, imgs[0], message=text)
        post_id = r.get("post_id") or r["id"]
    else:
        post_id = api("POST", f"{G}/{page}/feed", data={"message": text})["id"]
    if j.get("firstCommentText"):
        try:
            api("POST", f"{G}/{post_id}/comments", data={"message": j["firstCommentText"]})
        except MetaError as e:
            print(f"⚠️ первый комментарий не добавлен: {e}")
    return post_id


# ---------------- главное ----------------

def resolve_ids() -> tuple:
    """Страница и Instagram. В секрете может лежать токен страницы или бессрочный токен пользователя:
    во втором случае берём из него токен страницы Камилы (FB_PAGE_ID / page_id в publisher.json)."""
    global TOKEN
    page = os.environ.get("FB_PAGE_ID", "").strip() or str(CFG.get("page_id", ""))
    ig = os.environ.get("IG_USER_ID", "").strip() or str(CFG.get("ig_user_id", ""))
    if not page:
        page = api("GET", f"{G}/me", params={"fields": "id"})["id"]
    info = api("GET", f"{G}/{page}", params={"fields": "access_token,instagram_business_account"})
    if info.get("access_token"):
        TOKEN = info["access_token"]
    if not ig:
        ig = (info.get("instagram_business_account") or {}).get("id", "")
    return page, ig


def main():
    state = load_state()
    now = datetime.now(TZ)
    max_late = timedelta(hours=CFG.get("max_late_hours", 12))
    jobs = load_jobs()
    if ONLY:
        due = [j for j in jobs if j["id"] == ONLY or j["key"] == ONLY]
    else:
        due = [j for j in jobs if j["when"] <= now and j["id"] not in state["published"]
               and state["failed"].get(j["id"], {}).get("attempts", 0) < CFG.get("max_attempts", 3)]
    late = [j for j in due if now - j["when"] > max_late and not ONLY]
    for j in late:
        print(f"⏭ {j['id']}: опоздание больше {max_late}, пропускаю")
        state["failed"][j["id"]] = {"attempts": 99, "error": "слишком поздно", "at": now.isoformat(timespec="minutes")}
    due = [j for j in due if j not in late]
    print(f"🕐 {now:%Y-%m-%d %H:%M}, задач в очередях: {len(jobs)}, к публикации: {len(due)}")
    if not due:
        save_state(state)
        return
    if not TOKEN and not DRY_RUN:
        sys.exit("❌ Не задан секрет META_PAGE_TOKEN — см. automation/PUBLISHING.md")

    missing = [str(f.relative_to(ROOT)) for j in due for f in j["files"] if not f.exists()]
    if ensure_jpegs(due) and not DRY_RUN:
        git("add", "automation/jpg")
        git("commit", "-m", "🖼 JPEG для Instagram")
        git("pull", "--rebase")
        git("push")
    sha = git("rev-parse", "HEAD")

    if DRY_RUN:
        for j in due:
            print(f"🧪 {j['id']}: {j['network']} {j['type']} {j['when']:%d.%m %H:%M}, файлов {len(j['files'])}")
        if missing:
            print("⚠️ Нет файлов: " + ", ".join(missing))
        return

    page, ig = resolve_ids()
    print(f"📘 Страница {page}, 📸 Instagram {ig or 'не привязан'}")
    errors = []
    for j in due:
        try:
            absent = [f.name for f in j["files"] if not f.exists()]
            if absent:
                raise MetaError("нет файлов: " + ", ".join(absent))
            if j["network"] == "instagram":
                if not ig:
                    raise MetaError("к странице Facebook не привязан Instagram")
                pid = publish_instagram(j, ig, sha)
            elif j["network"] == "facebook":
                pid = publish_facebook(j, page)
            else:
                raise MetaError(f"неизвестная сеть {j['network']}")
            state["published"][j["id"]] = {"post_id": pid, "at": datetime.now(TZ).isoformat(timespec="minutes")}
            state["failed"].pop(j["id"], None)
            print(f"✅ {j['id']} → {pid}")
        except Exception as e:  # noqa: BLE001
            f = state["failed"].setdefault(j["id"], {"attempts": 0})
            f.update(attempts=f["attempts"] + 1, error=str(e)[:300], at=datetime.now(TZ).isoformat(timespec="minutes"))
            print(f"❌ {j['id']}: {e}")
            errors.append(f"{j['id']} (попытка {f['attempts']}): {e}")
        save_state(state)
    if errors:
        notify("⚠️ Публикатор Instagram/Facebook:\n" + "\n".join(errors))


if __name__ == "__main__":
    main()
