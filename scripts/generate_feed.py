import hashlib
import os
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from xml.dom import minidom


# ======================
# Config (ENV)
# ======================
SITE_URL = os.environ.get("SITE_URL", "https://www.heise.de/make/plus")
FEED_SELF_URL = os.environ.get("FEED_SELF_URL", "")
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "feed.xml")

CHANNEL_TITLE = os.environ.get("CHANNEL_TITLE", "Make Magazin: heise+ Artikel | heise online")
CHANNEL_DESC = os.environ.get("CHANNEL_DESC", "Aktuelle heise+ Artikel vom Make Magazin")
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://www.heise.de/make/plus/")
CHANNEL_IMAGE_URL = os.environ.get("CHANNEL_IMAGE_URL", "https://www.heise.de/make/icons/favicon.svg")
CHANNEL_LANGUAGE = os.environ.get("CHANNEL_LANGUAGE", "de")
GENERATOR = os.environ.get("GENERATOR", "https://github.com/MakeMagazinDE/Desktop-RSS-Reader")

MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "30"))

# ======================
# Helpers
# ======================
def rfc822(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt)

def stable_guid(link: str) -> str:
    return hashlib.sha256(link.encode("utf-8")).hexdigest()

# Entfernt Meta am Ende wie "... 29.12.2025 10:00 Uhr 12 Make Magazin" oder "... 2 Make Magazin"
META_TAIL_RE = re.compile(
    r"""
    \s+\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}\s+Uhr(?:\s+\d+)?\s*Make\s+Magazin\s*$ |
    \s+\d+\s+Make\s+Magazin\s*$ |
    \s+Make\s+Magazin\s*$
    """,
    re.VERBOSE,
)

def clean_meta_tail(text: str) -> str:
    return META_TAIL_RE.sub("", text).strip()

def split_title_teaser(text: str) -> tuple[str, str]:
    """
    heise liefert häufig: "<Titel> <Anrisstext> <Meta>"
    Nach Meta-Removal bleibt "<Titel> <Anrisstext>"
    Trennung ist nicht perfekt maschinenlesbar -> Heuristik:
      - Wenn 'Titel:' vorhanden, Titel = bis ':' (inkl. falls das ein echtes Titelmuster ist)
      - Sonst: Titel = bis ~80 Zeichen (an Wortgrenze), Rest = Anriss
    """
    t = clean_meta_tail(re.sub(r"\s+", " ", text).strip())
    if not t:
        return "", ""

    # 1) Gute Trennstelle: "Titel: Anrisstext"
    if ":" in t:
        left, right = t.split(":", 1)
        # nur nutzen, wenn links nicht zu kurz/lang
        if 10 <= len(left.strip()) <= 120 and len(right.strip()) >= 20:
            title = left.strip()
            teaser = right.strip()
            return title, teaser

    # 2) Wenn es einen klaren Satzbeginn im Rest gibt (Punkt)
    if "." in t:
        first_sentence, rest = t.split(".", 1)
        first_sentence = first_sentence.strip()
        rest = rest.strip()
        # Wenn der erste Satz relativ kurz ist, ist er oft der Titel
        if 10 <= len(first_sentence) <= 110 and len(rest) >= 20:
            return first_sentence, rest

    # 3) Fallback: hart schneiden
    if len(t) > 90:
        title = t[:80].rsplit(" ", 1)[0].strip()
        teaser = t[len(title):].strip()
        return title, teaser or t

    return t, t

def fetch_html(url: str) -> str:
    # Realistischer Browser-User-Agent + Accept-Language hilft gegen Bot/Minimal-Versionen
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    r = requests.get(url, timeout=30, headers=headers)
    r.raise_for_status()
    return r.text

def fetch_items() -> list[dict]:
    html = fetch_html(SITE_URL)
    soup = BeautifulSoup(html, "html.parser")

    items = []
    seen = set()

    # Heise-Seite zeigt Artikel-Links klar als <a> mit /ratgeber/… oder ähnlichem Pfad (und .html)
    # Wir filtern robust:
    candidates = soup.select('a[href]')
    for a in candidates:
        href = (a.get("href") or "").strip()
        if not href:
            continue

        # nur "Artikelartige" Links
        # (die Plus-Seite enthält sehr viele Navigation/Shop/Archiv-Links)
        if "/ratgeber/" not in href and "/news/" not in href and "/meldung/" not in href:
            continue
        if ".html" not in href:
            continue

        link = urljoin(SITE_URL, href)
        if link in seen:
            continue

        text = a.get_text(" ", strip=True)
        if not text or len(text) < 30:
            continue

        title, desc = split_title_teaser(text)
        if not title or len(title) < 10:
            continue

        seen.add(link)
        items.append({
            "title": title,
            "description": desc or title,
            "link": link,
            "guid": stable_guid(link),
            "pubdate": datetime.now(timezone.utc),
        })

        if len(items) >= MAX_ITEMS:
            break

    print(f"[generate_feed] Found {len(items)} items")
    return items


def add_text(doc, parent, tag, text, attrs=None, ns=None):
    el = doc.createElementNS(ns, tag) if ns else doc.createElement(tag)
    if attrs:
        for k, v in attrs.items():
            el.setAttribute(k, v)
    if text is not None:
        el.appendChild(doc.createTextNode(text))
    parent.appendChild(el)
    return el

def add_cdata(doc, parent, tag, cdata_text, attrs=None, ns=None):
    el = doc.createElementNS(ns, tag) if ns else doc.createElement(tag)
    if attrs:
        for k, v in attrs.items():
            el.setAttribute(k, v)
    el.appendChild(doc.createCDATASection(cdata_text))
    parent.appendChild(el)
    return el


def main():
    ATOM_NS = "http://www.w3.org/2005/Atom"
    DC_NS = "http://purl.org/dc/elements/1.1/"
    MEDIA_NS = "http://search.yahoo.com/mrss/"

    items = fetch_items()
    now = datetime.now(timezone.utc)

    doc = minidom.Document()

    rss = doc.createElement("rss")
    rss.setAttribute("version", "2.0")
    rss.setAttribute("xmlns:atom", ATOM_NS)
    rss.setAttribute("xmlns:dc", DC_NS)
    rss.setAttribute("xmlns:media", MEDIA_NS)
    doc.appendChild(rss)

    channel = doc.createElement("channel")
    rss.appendChild(channel)

    add_text(doc, channel, "title", CHANNEL_TITLE)
    add_text(doc, channel, "description", CHANNEL_DESC)
    add_text(doc, channel, "link", CHANNEL_LINK)

    if CHANNEL_IMAGE_URL:
        img = doc.createElement("image")
        channel.appendChild(img)
        add_text(doc, img, "url", CHANNEL_IMAGE_URL)
        add_text(doc, img, "title", CHANNEL_TITLE)
        add_text(doc, img, "link", CHANNEL_LINK)

    add_text(doc, channel, "generator", GENERATOR)
    add_text(doc, channel, "lastBuildDate", rfc822(now))

    if FEED_SELF_URL:
        atom_link = doc.createElementNS(ATOM_NS, "atom:link")
        atom_link.setAttribute("href", FEED_SELF_URL)
        atom_link.setAttribute("rel", "self")
        atom_link.setAttribute("type", "application/rss+xml")
        channel.appendChild(atom_link)

    add_text(doc, channel, "language", CHANNEL_LANGUAGE)

    for it in items:
        item = doc.createElement("item")
        channel.appendChild(item)

        add_text(doc, item, "title", it["title"])
        add_cdata(doc, item, "description", it["description"])
        add_text(doc, item, "link", it["link"])
        add_text(doc, item, "guid", it["guid"], attrs={"isPermaLink": "false"})
        add_text(doc, item, "pubDate", rfc822(it["pubdate"]))

        dc_creator = doc.createElementNS(DC_NS, "dc:creator")
        dc_creator.appendChild(doc.createTextNode(""))
        item.appendChild(dc_creator)

    with open(OUTPUT_PATH, "wb") as f:
        f.write(doc.toprettyxml(indent="  ", encoding="utf-8"))


if __name__ == "__main__":
    main()