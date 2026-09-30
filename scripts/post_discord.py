#!/usr/bin/env python3
"""Post a report file to Discord via webhook.

Usage: python3 scripts/post_discord.py REPORT_FILE [--wait-until HH:MM]

Reads the webhook URL from the DISCORD_WEBHOOK_URL environment variable.
Splits messages longer than Discord's 2000-character limit.
--wait-until sleeps until the given Asia/Tokyo time before posting.
"""
import argparse
import datetime as dt
import json
import os
import ssl
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

LIMIT = 1900


def chunks(text):
    out, buf = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > LIMIT:
            out.append(line[:LIMIT])
            line = line[LIMIT:]
        if len(buf) + len(line) > LIMIT:
            out.append(buf)
            buf = ""
        buf += line
    if buf.strip():
        out.append(buf)
    return out


def wait_until(hhmm):
    tz = ZoneInfo("Asia/Tokyo")
    now = dt.datetime.now(tz)
    h, m = map(int, hhmm.split(":"))
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    secs = (target - now).total_seconds()
    if 0 < secs < 3600:
        time.sleep(secs)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("report")
    p.add_argument("--wait-until")
    args = p.parse_args()

    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        sys.exit("DISCORD_WEBHOOK_URL is not set")
    with open(args.report, encoding="utf-8") as f:
        text = f.read()
    if args.wait_until:
        wait_until(args.wait_until)

    cafile = os.environ.get("SSL_CERT_FILE")
    if not cafile and os.path.exists("/root/.ccr/ca-bundle.crt"):
        cafile = "/root/.ccr/ca-bundle.crt"
    ctx = ssl.create_default_context(cafile=cafile)

    for part in chunks(text):
        req = urllib.request.Request(
            url,
            data=json.dumps({"content": part}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "ea-daily-report"},
        )
        urllib.request.urlopen(req, context=ctx).read()
        time.sleep(1)
    print("posted")


if __name__ == "__main__":
    main()
