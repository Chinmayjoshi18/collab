#!/usr/bin/env python3
import datetime as dt
import hashlib
import json
import os
import re
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List

UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)


@dataclass
class Story:
    source: str
    headline: str
    link: str
    published: dt.datetime
    summary: str


@dataclass
class ScoredStory:
    story: Story
    impact: str
    score: int
    affected: str
    why: str


FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Reuters", "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best"),
    ("SEC", "https://www.sec.gov/news/pressreleases.rss"),
    ("CFTC", "https://www.cftc.gov/PressRoom/PressReleases/rss"),
]

ASSET_KEYWORDS = {"BTC": ["bitcoin", "btc", "spot etf"], "ETH": ["ethereum", "eth"], "SOL": ["solana", "sol"], "Stablecoins": ["stablecoin", "usdt", "usdc"], "DeFi": ["defi", "dex", "aave", "uniswap"], "Exchanges": ["binance", "coinbase", "kraken", "bybit"], "AI tokens": ["ai token", "bittensor", "render"], "Memecoins": ["memecoin", "dogecoin", "shiba", "pepe"]}
POSITIVE = ["approval", "approved", "inflow", "launch", "adoption", "eases", "cuts"]
NEGATIVE = ["exploit", "hack", "lawsuit", "ban", "outflow", "delay", "rejection", "liquidation", "charges"]
HIGH_IMPACT = ["fed", "fomc", "cpi", "pce", "payroll", "etf", "sec", "cftc", "hack", "exploit", "tariff", "rates"]

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8661874883:AAEHcDfts5xwrAJalq7YQdvw0LzgxmMwCCE")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@VIPCryptoTradersSignal")
STATE_PATH = Path(os.getenv("ALERT_STATE_PATH", ".cache/sent_stories.json"))
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def fetch_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "crypto-market-alert-bot/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def text_of(elem, names):
    for n in names:
        child = elem.find(n)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def parse_date(raw: str) -> dt.datetime:
    if not raw:
        return NOW
    try:
        return parsedate_to_datetime(raw).astimezone(UTC)
    except Exception:
        return NOW


def parse_rss(source: str, body: bytes, cutoff: dt.datetime) -> List[Story]:
    root = ET.fromstring(body)
    items = root.findall(".//item")
    stories = []
    for it in items[:30]:
        pub = parse_date(text_of(it, ["pubDate", "published", "updated"]))
        if pub < cutoff:
            continue
        title = text_of(it, ["title"]) or "(no headline)"
        link = text_of(it, ["link"])
        desc = re.sub("<[^>]+>", "", text_of(it, ["description", "summary"]))
        stories.append(Story(source, title, link, pub, desc))
    return stories


def fetch_recent_stories(hours=8):
    cutoff = NOW - dt.timedelta(hours=hours)
    out = []
    for source, url in FEEDS:
        try:
            out.extend(parse_rss(source, fetch_url(url), cutoff))
        except Exception:
            continue
    return out


def assess(s: Story) -> ScoredStory:
    text = f"{s.headline} {s.summary}".lower()
    affected = [k for k, kws in ASSET_KEYWORDS.items() if any(w in text for w in kws)] or ["Broader crypto market"]
    pos, neg = sum(x in text for x in POSITIVE), sum(x in text for x in NEGATIVE)
    impact = "mixed" if pos == neg else ("positive" if pos > neg else "negative")
    score = 3 + (2 if any(k in text for k in HIGH_IMPACT) else 0) + (1 if any(k in text for k in ["billion", "etf", "sec", "fed", "cpi", "rates", "hack"]) else 0)
    score = max(1, min(score, 10))
    why = f"This is fresh from {s.source} ({s.published.strftime('%Y-%m-%d %H:%M UTC')}) and may shift risk sentiment or regulatory expectations. Traders can rapidly reprice {', '.join(affected[:3])}, with spillover into majors and altcoins."
    return ScoredStory(s, impact, score, ", ".join(affected), why)


def sid(story: Story):
    return hashlib.sha256(f"{story.headline}|{story.link}".encode()).hexdigest()[:20]


def load_state():
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def send(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": msg, "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def main():
    stories = [assess(s) for s in fetch_recent_stories()]
    picks = sorted([x for x in stories if x.score > 5], key=lambda x: x.story.published, reverse=True)
    state = load_state()
    cutoff = NOW - dt.timedelta(hours=24)
    state = {k: v for k, v in state.items() if dt.datetime.fromisoformat(v) > cutoff}
    sent = 0
    for p in picks:
        k = sid(p.story)
        if k in state:
            continue
        msg = textwrap.dedent(f"""Crypto Market Alert
Headline: {p.story.headline}
Impact: {p.impact} | Score: {p.score}
Affected: {p.affected}
Why it matters: {p.why}
Source: {p.story.link}""")
        send(msg)
        state[k] = NOW.isoformat()
        sent += 1
    STATE_PATH.write_text(json.dumps(state, indent=2))
    print("No qualifying market-moving story found (impact > 5)." if sent == 0 else f"Sent {sent} alert(s) to Telegram.")


if __name__ == "__main__":
    main()
