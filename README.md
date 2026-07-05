# Quantum stock news agent (runs locally on your machine)

## Files
- `quantum_watchlist_config.json` — your list of tickers. Edit this in any text editor to add/remove stocks.
- `check_quantum_news.py` — pulls recent Yahoo Finance headlines per ticker, then sends them to Claude to judge which ones are actually significant, summarize why, and rank urgency. This is what makes it an agent rather than a plain fetch-and-print script — it's making a judgment call, not just listing everything it finds.

## Setup
```
pip install yfinance anthropic
```

You'll also need an Anthropic API key (from console.anthropic.com):
```
export ANTHROPIC_API_KEY=your_key_here      # Mac/Linux
setx ANTHROPIC_API_KEY "your_key_here"       # Windows (open a new terminal after)
```

## Run it
```
python check_quantum_news.py
```

This fetches raw headlines, has Claude filter out noise and keep only material
news (earnings, contracts, funding, partnerships, regulatory changes, analyst
actions, technical breakthroughs), prints the significant ones with a urgency
tag and one-line reasoning, and updates `last_checked` in the JSON file.

## Getting real notifications (not just on-demand)
This script only checks when you run it. To get actual alerts:
1. Schedule it to run automatically:
   - **Mac/Linux**: add a line to `crontab -e`, e.g. every hour:
     `0 * * * * cd /path/to/folder && python3 check_quantum_news.py >> log.txt`
   - **Windows**: use Task Scheduler to run it on a schedule.
2. Edit the `notify()` function in `check_quantum_news.py` to send yourself an
   email, Slack message, or push notification instead of just printing —
   for example using `smtplib` for email or a webhook URL for Slack.

## Editing your watchlist
Open `quantum_watchlist_config.json` and add a new entry like:
```json
{ "symbol": "IBM", "name": "IBM" }
```
