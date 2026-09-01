#!/usr/bin/env python3
"""Normalize a day token to YYYY-MM-DD (machine-local). Unparseable -> exit 1."""
import sys, datetime

raw = " ".join(sys.argv[1:]).strip().lower()
today = datetime.date.today()

if raw in ("", "today"):
    print(today); sys.exit()
if raw == "yesterday":
    print(today - datetime.timedelta(days=1)); sys.exit()

for fmt in ("%Y-%m-%d", "%m-%d", "%m/%d", "%B %d", "%b %d",
            "%B %d %Y", "%b %d %Y", "%d %B", "%d %b"):
    # A year-less format is parsed with the current year supplied explicitly:
    # letting strptime default the year is deprecated and mishandles Feb 29.
    text, form = (raw, fmt) if "%Y" in fmt else (f"{raw} {today.year}", f"{fmt} %Y")
    try:
        print(datetime.datetime.strptime(text, form).date()); sys.exit()
    except ValueError:
        pass

print(f"UNPARSEABLE: {raw!r}", file=sys.stderr)
sys.exit(1)
