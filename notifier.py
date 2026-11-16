"""Watches ss.com RSS feeds and sends matching ads to Telegram."""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

FEEDS = [
    "https://www.ss.com/lv/entertainment/music/musical-instrument/wind/rss/",
]

# Lowercase substrings matched against title, brand and model
KEYWORDS = [
    "sakso", "sax", "саксоф",           # saxophone: lv / en / ru+ua
    "trompet", "trumpet", "труб",       # trumpet
]

LABELS = {"Marka": "Марка", "Modelis": "Модель", "Stāv.": "Стан", "Cena": "Ціна"}

SEEN_FILE = Path(__file__).with_name("seen.json")
SEEN_LIMIT = 1000
USER_AGENT = "Mozilla/5.0 (ss-notifier)"

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def parse_feed(xml_bytes):
    ads = []
    for item in ET.fromstring(xml_bytes).iter("item"):
        link = item.findtext("link", "").strip()
        desc = item.findtext("description", "")
        # Values come as <b>x</b> or <b><b>x</b> €</b>, so split by <br/> and strip all tags
        fields = {}
        for part in desc.split("<br/>"):
            label, sep, value = re.sub(r"<[^>]+>", "", part).partition(":")
            if sep and label.strip() in LABELS:
                fields[label.strip()] = re.sub(r"\s+", " ", value).strip()
        photo = re.search(r'src="([^"]+)\.t\.jpg"', desc)
        ads.append({
            "id": link.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html"),
            "link": link,
            "title": item.findtext("title", "").strip(),
            "fields": fields,
            # .t.jpg is a 174px thumbnail, .800.jpg is the full photo
            "photo": photo.group(1) + ".800.jpg" if photo else None,
        })
    return ads


def matches(ad):
    text = " ".join([ad["title"], ad["fields"].get("Marka", ""), ad["fields"].get("Modelis", "")]).lower()
    return any(k in text for k in KEYWORDS)


def caption(ad):
    lines = ["✨ <b>Нове оголошення на SS.COM</b>", "", html.escape(ad["title"]), ""]
    for lv, ua in LABELS.items():
        if lv in ad["fields"]:
            lines.append(f"• {ua}: <b>{html.escape(ad['fields'][lv])}</b>")
    lines += ["", f'<a href="{ad["link"]}">Відкрити оголошення</a>']
    return "\n".join(lines)


def telegram(method, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def send(ad):
    text = caption(ad)
    if not TOKEN:
        print(f"--- DRY RUN ({ad['photo']})\n{text}\n")
        return
    base = {"chat_id": CHAT_ID, "parse_mode": "HTML"}
    if ad["photo"]:
        try:
            telegram("sendPhoto", {**base, "photo": ad["photo"], "caption": text})
            return
        except Exception as e:
            print(f"sendPhoto failed for {ad['id']}: {e}, falling back to text", file=sys.stderr)
    telegram("sendMessage", {**base, "text": text})


def main():
    seen = json.loads(SEEN_FILE.read_text("utf-8")) if SEEN_FILE.exists() else []
    seen_set = set(seen)

    new_ads = []
    for url in FEEDS:
        try:
            new_ads += [a for a in parse_feed(fetch(url)) if a["id"] not in seen_set and matches(a)]
        except Exception as e:
            print(f"Feed failed {url}: {e}", file=sys.stderr)

    # Feed is newest first, send oldest first
    for ad in reversed(new_ads):
        send(ad)
        seen.append(ad["id"])
        seen_set.add(ad["id"])
        time.sleep(1)

    print(f"Sent {len(new_ads)} new ad(s)")
    if TOKEN:
        SEEN_FILE.write_text(json.dumps(seen[-SEEN_LIMIT:], indent=0), "utf-8")


if __name__ == "__main__":
    main()
