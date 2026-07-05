#!/usr/bin/env python3
"""
Quantum stock news agent.

Reads tickers from quantum_watchlist_config.json (same folder), pulls recent
Yahoo Finance news for each one, then sends the raw headlines to Claude to
decide which ones actually matter, summarize why, and flag anything urgent.
This reasoning step is what makes it an agent rather than a plain fetch-and-print
script -- it makes a judgment call instead of just dumping every headline.

Setup (one time):
    pip install yfinance anthropic
    export ANTHROPIC_API_KEY=your_key_here      (Mac/Linux)
    setx ANTHROPIC_API_KEY "your_key_here"       (Windows, new terminal after)

Usage:
    python check_quantum_news.py

To add/remove tickers, just edit quantum_watchlist_config.json in a text editor.

To get real "push" notifications (not just when you run this manually),
schedule this script with cron (Mac/Linux) or Task Scheduler (Windows),
and change notify() below to send an email/Slack message/etc.
"""

import importlib
import json
import os
from datetime import datetime

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("Missing dependency. Run: pip install yfinance")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quantum_watchlist_config.json")
MODEL = "claude-sonnet-4-6"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def fetch_raw_news(tickers):
    """Pull recent headlines per ticker from Yahoo Finance via yfinance."""
    raw = []
    for entry in tickers:
        symbol = entry["symbol"]
        name = entry.get("name", symbol)
        try:
            stock = yf.Ticker(symbol)
            news_items = stock.news or []
        except Exception as e:
            print(f"[{symbol}] Could not fetch news: {e}")
            continue

        for item in news_items[:5]:
            content = item.get("content", item)  # yfinance versions vary
            headline = content.get("title") or item.get("title", "(no title)")
            link = (content.get("canonicalUrl") or {}).get("url") or item.get("link", "")
            raw.append({"ticker": symbol, "name": name, "headline": headline, "link": link})
    return raw


def analyze_with_claude(raw_news):
    """Ask Claude to judge which headlines are actually significant and summarize why."""
    if not raw_news:
        return []

    try:
        anthropic = importlib.import_module("anthropic")
    except ImportError:
        raise SystemExit("Missing dependency. Run: pip install anthropic")

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    prompt = f"""You are a stock news analyst. Below is a list of raw headlines
scraped from Yahoo Finance for a quantum computing stock watchlist.

Your job:
1. Ignore filler, duplicates, or routine noise (minor price moves with no cause, generic "stock watch" articles).
2. Keep only headlines that reflect something material: earnings, contracts, funding, partnerships, regulatory news, executive changes, major analyst actions, or technical breakthroughs.
3. For each one you keep, write a one-sentence plain-English summary of why it matters, in your own words.
4. Assign urgency: "high" (likely to move the stock meaningfully or requires attention soon), "medium", or "low".
5. Score sentiment from the shareholder's point of view on an integer scale from -5 (very bad news, e.g. fraud, missed earnings, downgrade) to +5 (very good news, e.g. major contract win, beat-and-raise, breakthrough). Use 0 for genuinely neutral/mixed news.

Raw headlines (JSON):
{json.dumps(raw_news, indent=2)}

Respond with ONLY a JSON array, no markdown fences, no preamble, in this exact format:
[{{"ticker": "IONQ", "headline": "...", "why_it_matters": "...", "urgency": "high", "sentiment": 3}}]
If nothing is significant, return an empty array []."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    text = "".join(block.text for block in response.content if block.type == "text")
    cleaned = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        print("Could not parse Claude's response as JSON. Raw output:")
        print(text)
        return []


def sentiment_label(score):
    """Turn the -5..+5 sentiment score into a short readable tag."""
    try:
        score = int(score)
    except (TypeError, ValueError):
        return ""
    if score >= 4:
        word = "very positive"
    elif score >= 1:
        word = "positive"
    elif score == 0:
        word = "neutral"
    elif score >= -3:
        word = "negative"
    else:
        word = "very negative"
    return f"sentiment {score:+d} ({word})"


def notify(item):
    """Replace this with an email/SMS/Slack call if you want real alerts."""
    urgency_flag = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}.get(item.get("urgency", "low"), "")
    print(f"\n{urgency_flag} [{item['ticker']}] {item['headline']}")
    print(f"  Why it matters: {item['why_it_matters']}")
    tag = sentiment_label(item.get("sentiment"))
    if tag:
        print(f"  Sentiment: {tag}")


def main():
    config = load_config()
    tickers = config.get("tickers", [])

    if not tickers:
        print("No tickers in quantum_watchlist_config.json. Add some and re-run.")
        return

    print(f"Fetching news for {len(tickers)} ticker(s)...")
    raw_news = fetch_raw_news(tickers)

    if not raw_news:
        print("No recent news found for your watchlist.")
    else:
        print(f"Found {len(raw_news)} raw headline(s). Asking Claude to filter for significance...")
        significant = analyze_with_claude(raw_news)

        if not significant:
            print("\nClaude reviewed the headlines and found nothing significant right now.")
        else:
            # Group items by ticker; keep watchlist order for the groups,
            # and within each group show high urgency first.
            order = {"high": 0, "medium": 1, "low": 2}
            by_ticker = {}
            for item in significant:
                by_ticker.setdefault(item.get("ticker", "?"), []).append(item)

            watchlist_order = [t["symbol"] for t in tickers]
            group_symbols = sorted(
                by_ticker.keys(),
                key=lambda s: watchlist_order.index(s) if s in watchlist_order else len(watchlist_order),
            )

            name_by_symbol = {t["symbol"]: t.get("name", t["symbol"]) for t in tickers}
            for symbol in group_symbols:
                items = sorted(by_ticker[symbol], key=lambda x: order.get(x.get("urgency", "low"), 2))
                print(f"\n=== {symbol} ({name_by_symbol.get(symbol, symbol)}) — {len(items)} item(s) ===")
                for item in items:
                    notify(item)

    config["last_checked"] = datetime.now().isoformat(timespec="seconds")
    save_config(config)


if __name__ == "__main__":
    main()
