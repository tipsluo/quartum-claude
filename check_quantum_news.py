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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "quantum_watchlist_config.json")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
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


def analyze_with_claude(raw_news, watchlist):
    """Ask Claude to judge which headlines are significant and rate the impact on every affected stock."""
    if not raw_news:
        return []

    try:
        anthropic = importlib.import_module("anthropic")
    except ImportError:
        raise SystemExit("Missing dependency. Run: pip install anthropic")

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    watchlist_desc = ", ".join(f'{t["symbol"]} ({t.get("name", t["symbol"])})' for t in watchlist)

    prompt = f"""You are a stock news analyst. Below is a list of raw headlines
scraped from Yahoo Finance for a quantum computing stock watchlist.

The watchlist stocks are: {watchlist_desc}

Your job:
1. Ignore filler, duplicates, or routine noise (minor price moves with no cause, generic "stock watch" articles).
2. Keep only headlines that reflect something material: earnings, contracts, funding, partnerships, regulatory news, executive changes, major analyst actions, or technical breakthroughs.
3. For each one you keep, write a one-sentence plain-English summary of why it matters, in your own words.
4. Assign urgency: "high" (likely to move a stock meaningfully or requires attention soon), "medium", or "low".
5. Identify EVERY watchlist stock the news is relevant to -- not only the ticker it was filed under. One headline can affect several stocks (e.g. sector-wide news moves all of them; a contract won by one competitor can hurt another). List an entry only for stocks that are genuinely affected.
6. For each affected stock, write a one-sentence plain-English "effect" describing how it bears on that stock, then score two SEPARATE things:
   - "sentiment": how good or bad the news is for that stock's shareholders, as an integer from -5 (very bad, e.g. fraud, missed earnings, downgrade) to +5 (very good, e.g. major contract win, beat-and-raise, breakthrough). Use 0 for genuinely neutral/mixed. The same headline can be positive for one stock and negative for another.
   - "impact": how much this news is likely to affect the stock's price GOING FORWARD, as an integer from 0 to 5. This is forward-looking and about NEW information, not how dramatic the event was. Backward-looking recaps of things that already happened and are already priced in (e.g. "Why IonQ Stock Plummeted 26.1% in June") get a LOW impact (0-1) even if sentiment is strongly negative, because they change nothing about the future. New, unpriced developments (a just-announced contract, guidance change, breakthrough, investigation) get a HIGH impact (4-5).
Sentiment and impact are independent: strong sentiment with low impact (old/priced-in news) and mild sentiment with high impact (an early signal) are both common.

Raw headlines (JSON):
{json.dumps(raw_news, indent=2)}

Respond with ONLY a JSON array, no markdown fences, no preamble, in this exact format:
[{{"headline": "...", "why_it_matters": "...", "urgency": "high", "impacts": [{{"ticker": "IONQ", "effect": "...", "sentiment": 3, "impact": 4}}, {{"ticker": "RGTI", "effect": "...", "sentiment": -1, "impact": 2}}]}}]
If nothing is significant, return an empty array []."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "max_tokens":
        print("Warning: Claude's response hit the max_tokens limit and was cut off; "
              "results may be incomplete. Consider raising max_tokens or trimming the watchlist.")

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


def impact_label(score):
    """Turn the 0..5 forward-looking impact score into a short readable tag."""
    try:
        score = int(score)
    except (TypeError, ValueError):
        return ""
    if score >= 4:
        word = "high"
    elif score >= 2:
        word = "moderate"
    elif score == 1:
        word = "low"
    else:
        word = "negligible"
    return f"impact {score}/5 ({word})"


def format_item(item):
    """Build the human-readable lines for one news item."""
    urgency_flag = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}.get(item.get("urgency", "low"), "")
    lines = [f"{urgency_flag} {item['headline']}", f"  Why it matters: {item['why_it_matters']}"]
    impacts = item.get("impacts", [])
    if impacts:
        lines.append("  Impact by stock:")
        for impact in impacts:
            tags = [t for t in (sentiment_label(impact.get("sentiment")), impact_label(impact.get("impact"))) if t]
            suffix = f" [{', '.join(tags)}]" if tags else ""
            lines.append(f"    {impact.get('ticker', '?')}: {impact.get('effect', '')}{suffix}")
    return "\n".join(lines)


def notify(item):
    """Replace this with an email/SMS/Slack call if you want real alerts."""
    print("\n" + format_item(item))


def summarize_by_stock(significant, tickers):
    """Roll up every news item's impact per stock into a digest section."""
    # Collect each (headline, effect, sentiment, impact) entry per ticker.
    by_stock = {}
    for item in significant:
        for impact in item.get("impacts", []):
            symbol = impact.get("ticker", "?")
            by_stock.setdefault(symbol, []).append({
                "headline": item.get("headline", ""),
                "effect": impact.get("effect", ""),
                "sentiment": impact.get("sentiment"),
                "impact": impact.get("impact"),
            })

    def as_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    name_by_symbol = {t["symbol"]: t.get("name", t["symbol"]) for t in tickers}
    # Keep watchlist order, then any extra symbols Claude referenced.
    ordered = [t["symbol"] for t in tickers if t["symbol"] in by_stock]
    ordered += [s for s in by_stock if s not in ordered]

    lines = ["=== Summary by stock ==="]
    for symbol in ordered:
        entries = sorted(by_stock[symbol], key=lambda e: as_int(e["impact"]), reverse=True)
        net_sentiment = sum(as_int(e["sentiment"]) for e in entries)
        max_impact = max(as_int(e["impact"]) for e in entries)
        name = name_by_symbol.get(symbol, symbol)
        lines.append(
            f"\n{symbol} ({name}): {len(entries)} item(s) | "
            f"net {sentiment_label(net_sentiment)} | top {impact_label(max_impact)}"
        )
        for e in entries:
            tags = [t for t in (sentiment_label(e["sentiment"]), impact_label(e["impact"])) if t]
            suffix = f" [{', '.join(tags)}]" if tags else ""
            lines.append(f"  - {e['effect']}{suffix}")
    return "\n".join(lines)


def save_report(text, timestamp):
    """Write the report text to a timestamped file in the reports directory."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    safe_stamp = timestamp.replace(":", "-")
    path = os.path.join(REPORTS_DIR, f"quantum_news_{safe_stamp}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def main():
    config = load_config()
    tickers = config.get("tickers", [])

    if not tickers:
        print("No tickers in quantum_watchlist_config.json. Add some and re-run.")
        return

    timestamp = datetime.now().isoformat(timespec="seconds")

    print(f"Fetching news for {len(tickers)} ticker(s)...")
    raw_news = fetch_raw_news(tickers)

    report_parts = [f"Quantum stock news report -- {timestamp}"]

    if not raw_news:
        print("No recent news found for your watchlist.")
        report_parts.append("No recent news found for your watchlist.")
    else:
        print(f"Found {len(raw_news)} raw headline(s). Asking Claude to filter for significance...")
        significant = analyze_with_claude(raw_news, tickers)

        if not significant:
            msg = "Claude reviewed the headlines and found nothing significant right now."
            print("\n" + msg)
            report_parts.append(msg)
        else:
            # Sort so high urgency shows first
            order = {"high": 0, "medium": 1, "low": 2}
            significant.sort(key=lambda x: order.get(x.get("urgency", "low"), 2))
            for item in significant:
                notify(item)
                report_parts.append(format_item(item))

            summary = summarize_by_stock(significant, tickers)
            print("\n" + summary)
            report_parts.append(summary)

    report_path = save_report("\n\n".join(report_parts) + "\n", timestamp)
    print(f"\nReport saved to {report_path}")

    config["last_checked"] = timestamp
    save_config(config)


if __name__ == "__main__":
    main()
