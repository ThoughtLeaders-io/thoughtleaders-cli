#!/usr/bin/env python3
"""
Pull a brand's sold sponsorships in a date range, compute live vs sold-date eCPM,
also pull future bookings, build per-deal and per-channel views, upload a
two-tab Google Sheet, and print a top-10 markdown summary.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "brand"


def to_float(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def to_int(x):
    f = to_float(x)
    return int(f) if f is not None else None


def youtube_url(article_id):
    if not article_id or ":" not in article_id:
        return ""
    vid = article_id.split(":", 1)[1]
    return f"https://www.youtube.com/watch?v={vid}"


def fmt_money(x):
    return f"${x:,.0f}" if x is not None else "n/a"


def fmt_int(x):
    return f"{x:,}" if x is not None else "n/a"


def fmt_ratio(x):
    return f"{x:.2f}x" if x is not None else "n/a"


def fmt_cpm(x):
    return f"${x:,.2f}" if x is not None else "n/a"


def tl_list(*args) -> list[dict]:
    rows: list[dict] = []
    limit = 200
    offset = 0
    while True:
        out = subprocess.run(
            ["tl", "sponsorships", "list", *args,
             "--limit", str(limit), "--offset", str(offset), "--json"],
            capture_output=True, text=True, check=True,
        ).stdout
        data = json.loads(out)
        page = data.get("results", data) if isinstance(data, dict) else data
        if not page:
            break
        rows.extend(page)
        if len(page) < limit:
            break
        offset += limit
    return rows


def fetch_future_bookings(brand: str) -> dict[str, dict]:
    """Return channel -> {scheduled_date, status} for the earliest future booking per channel.
    Future = scheduled_date strictly after today, status sold, or open with the brand
    having reviewed it (brand_approval pending or approved).
    """
    today = date.today()
    cutoff = (today + timedelta(days=1)).isoformat()
    end = (today + timedelta(days=365 * 2)).isoformat()
    rows: list[dict] = []
    # sold deals: a plain status filter.
    # open deals only count when the brand has reviewed them — narrow the OPEN
    # arm with brand_approval (pending or approved); a bare status:open would
    # over-count cold/un-reviewed open deals.
    queries = (
        ("sold", []),
        ("open", ["brand_approval:PENDING,APPROVED"]),
    )
    for status, extra in queries:
        rows.extend(tl_list(
            f"brand:{brand}",
            f"status:{status}",
            *extra,
            f"scheduled-date-start:{cutoff}",
            f"scheduled-date-end:{end}",
        ))
    by_channel: dict[str, dict] = {}
    for r in rows:
        ch = r.get("channel")
        sd = r.get("scheduled_date")
        st = r.get("status")
        if not ch or not sd:
            continue
        if ch not in by_channel or sd < by_channel[ch]["scheduled_date"]:
            by_channel[ch] = {"scheduled_date": sd, "status": st}
    return by_channel


def build_deal_rows(raw: list[dict], future: dict[str, dict]) -> list[dict]:
    out = []
    for r in raw:
        price = to_float(r.get("price"))
        promised = to_int(r.get("projected_views_at_purchase_date"))
        views = to_int(r.get("views"))
        publish_date = r.get("publish_date")
        live_cpm = (price / views * 1000) if (price and views) else None
        sold_cpm = (price / promised * 1000) if (price and promised) else None
        ratio = (views / promised) if (views and promised) else None
        delta = (live_cpm - sold_cpm) if (live_cpm is not None and sold_cpm is not None) else None
        measurable = bool(publish_date and views)
        ch = r.get("channel")
        f = future.get(ch)
        next_booking = f"{f['scheduled_date']} ({f['status']})" if f else "Re-book - no future spot"
        out.append({
            "channel": ch,
            "title": (r.get("title") or "").strip(),
            "video_url": youtube_url(r.get("article_id")),
            "scheduled_date": r.get("scheduled_date"),
            "publish_date": publish_date,
            "price": price,
            "price_currency": r.get("price_currency", "USD"),
            "promised_views": promised,
            "live_views": views,
            "view_ratio": ratio,
            "sold_date_ecpm": sold_cpm,
            "live_ecpm": live_cpm,
            "delta_ecpm": delta,
            "measurable": measurable,
            "next_booking": next_booking,
        })
    return out


def build_channel_rows(deals: list[dict], future: dict[str, dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for d in deals:
        ch = d["channel"] or "(unknown)"
        a = agg.setdefault(ch, {"deals": 0, "measurable": 0, "price": 0.0, "promised": 0.0, "live": 0.0})
        a["deals"] += 1
        a["price"] += d["price"] or 0
        if d["promised_views"]:
            a["promised"] += d["promised_views"]
        if d["live_views"]:
            a["live"] += d["live_views"]
            a["measurable"] += 1
    out = []
    for ch, a in agg.items():
        live_cpm = (a["price"] / a["live"] * 1000) if (a["live"] and a["price"]) else None
        sold_cpm = (a["price"] / a["promised"] * 1000) if (a["promised"] and a["price"]) else None
        ratio = (a["live"] / a["promised"]) if a["promised"] and a["live"] else None
        delta = (live_cpm - sold_cpm) if (live_cpm is not None and sold_cpm is not None) else None
        f = future.get(ch)
        next_booking = f"{f['scheduled_date']} ({f['status']})" if f else "Re-book - no future spot"
        out.append({
            "channel": ch,
            "deals": a["deals"],
            "measurable_deals": a["measurable"],
            "total_price": a["price"],
            "total_promised": int(a["promised"]),
            "total_live": int(a["live"]),
            "view_ratio": ratio,
            "sold_date_ecpm": sold_cpm,
            "live_ecpm": live_cpm,
            "delta_ecpm": delta,
            "next_booking": next_booking,
        })
    out.sort(key=lambda r: (r["live_ecpm"] is None, r["live_ecpm"] if r["live_ecpm"] is not None else 0))
    return out


def whoami_email() -> str | None:
    try:
        out = subprocess.run(["tl", "whoami", "--json"], capture_output=True, text=True, check=True).stdout
        return json.loads(out).get("user", {}).get("email")
    except Exception:
        return None


def gws(cmd: list[str], params: dict | None = None, body: dict | None = None) -> dict:
    args = ["gws", *cmd]
    if params is not None:
        args += ["--params", json.dumps(params)]
    if body is not None:
        args += ["--json", json.dumps(body)]
    r = subprocess.run(args, capture_output=True, text=True, check=True)
    # gws may print non-JSON preamble like "Using keyring backend: keyring" — find the JSON block
    out = r.stdout
    start = out.find("{")
    return json.loads(out[start:]) if start >= 0 else {}


def upload_sheet(brand: str, deals: list[dict], channels: list[dict], rankable: list[dict]) -> str:
    title = f"{brand} Top Partnerships ({deals[0]['scheduled_date'][:4] if deals else 'no-data'})"

    # 1) Create empty spreadsheet via Sheets API
    sheet = gws(["sheets", "spreadsheets", "create"], body={
        "properties": {"title": title},
        "sheets": [
            {"properties": {"title": "By Deal"}},
            {"properties": {"title": "By Channel"}},
        ],
    })
    sid = sheet["spreadsheetId"]

    # 2) Write By Deal
    deal_header = ["rank", "channel", "title", "video_url", "scheduled_date", "publish_date",
                   "price", "promised_views", "live_views", "view_ratio",
                   "sold_date_ecpm", "live_ecpm", "delta_ecpm", "measurable", "next_booking"]
    rank_ids = {id(d): i + 1 for i, d in enumerate(rankable)}
    # Order: ranked first (best live_ecpm), then unranked-measurable, then unmeasurable
    ranked_set = {id(d) for d in rankable}
    measurable_unranked = [d for d in deals if d["measurable"] and id(d) not in ranked_set]
    unmeasurable = [d for d in deals if not d["measurable"]]
    ordered = rankable + measurable_unranked + unmeasurable

    deal_values = [deal_header]
    for d in ordered:
        deal_values.append([
            rank_ids.get(id(d), ""),
            d["channel"] or "", d["title"], d["video_url"], d["scheduled_date"] or "",
            (d["publish_date"] or "")[:10], d["price"] or "",
            d["promised_views"] or "", d["live_views"] or "",
            round(d["view_ratio"], 4) if d["view_ratio"] is not None else "",
            round(d["sold_date_ecpm"], 4) if d["sold_date_ecpm"] is not None else "",
            round(d["live_ecpm"], 4) if d["live_ecpm"] is not None else "",
            round(d["delta_ecpm"], 4) if d["delta_ecpm"] is not None else "",
            "TRUE" if d["measurable"] else "FALSE",
            d["next_booking"],
        ])
    gws(["sheets", "spreadsheets", "values", "update"],
        params={"spreadsheetId": sid, "range": f"'By Deal'!A1:O{len(deal_values)}",
                "valueInputOption": "RAW"},
        body={"values": deal_values})

    # 3) Write By Channel
    ch_header = ["channel", "deals", "measurable_deals", "total_price_usd",
                 "total_promised_views", "total_live_views", "view_ratio",
                 "sold_date_ecpm", "live_ecpm", "delta_ecpm", "next_booking"]
    ch_values = [ch_header]
    for c in channels:
        ch_values.append([
            c["channel"], c["deals"], c["measurable_deals"],
            round(c["total_price"], 2), c["total_promised"], c["total_live"],
            round(c["view_ratio"], 4) if c["view_ratio"] is not None else "",
            round(c["sold_date_ecpm"], 4) if c["sold_date_ecpm"] is not None else "",
            round(c["live_ecpm"], 4) if c["live_ecpm"] is not None else "",
            round(c["delta_ecpm"], 4) if c["delta_ecpm"] is not None else "",
            c["next_booking"],
        ])
    gws(["sheets", "spreadsheets", "values", "update"],
        params={"spreadsheetId": sid, "range": f"'By Channel'!A1:K{len(ch_values)}",
                "valueInputOption": "RAW"},
        body={"values": ch_values})

    # 4) Share with the caller (writer, no email)
    email = whoami_email()
    if email:
        try:
            gws(["drive", "permissions", "create"],
                params={"fileId": sid, "sendNotificationEmail": False},
                body={"role": "writer", "type": "user", "emailAddress": email})
        except Exception:
            pass

    return f"https://docs.google.com/spreadsheets/d/{sid}/edit"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--scheduled-date-start", required=True)
    ap.add_argument("--scheduled-date-end", required=True)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    raw = tl_list(
        "status:sold", f"brand:{args.brand}",
        f"scheduled-date-start:{args.scheduled_date_start}", f"scheduled-date-end:{args.scheduled_date_end}",
    )
    future = fetch_future_bookings(args.brand)
    deals = build_deal_rows(raw, future)
    channels = build_channel_rows(deals, future)

    rankable = [d for d in deals if d["measurable"] and d["live_ecpm"] is not None and d["sold_date_ecpm"] is not None]
    rankable.sort(key=lambda d: d["live_ecpm"])

    measurable_count = sum(1 for d in deals if d["measurable"] and d["live_ecpm"] is not None)
    unmeasurable_count = sum(1 for d in deals if not d["measurable"])

    print("## Summary\n")
    print(f"- Sold sponsorships in range: **{len(deals)}**")
    print(f"- Measurable (video live with views): **{measurable_count}**")
    if rankable:
        median = sorted(d["live_ecpm"] for d in rankable)[len(rankable) // 2]
        overperformed = sum(1 for d in rankable if d["delta_ecpm"] is not None and d["delta_ecpm"] < 0)
        print(f"- Median live eCPM: **{fmt_cpm(median)}**")
        print(f"- Deals that overperformed: **{overperformed} / {len(rankable)}**")
    print()

    if channels:
        ranked_channels = [c for c in channels if c["live_ecpm"] is not None]
        print(f"## Top {min(args.top, len(ranked_channels))} channels by combined live eCPM\n")
        print("| # | Channel | Deals | Total spend | Total live views | View ratio | Live eCPM | Delta | Next booking |")
        print("|---|---------|-------|-------------|------------------|------------|-----------|-------|--------------|")
        for i, c in enumerate(ranked_channels[: args.top], 1):
            next_cell = c["next_booking"]
            if next_cell.startswith("Re-book"):
                next_cell = f"**{next_cell}**"
            print(
                f"| {i} | {c['channel']} | {c['deals']} | {fmt_money(c['total_price'])} | "
                f"{fmt_int(c['total_live'])} | {fmt_ratio(c['view_ratio'])} | "
                f"{fmt_cpm(c['live_ecpm'])} | {fmt_cpm(c['delta_ecpm'])} | {next_cell} |"
            )
        print()

    if unmeasurable_count:
        print(f"_{unmeasurable_count} deals in range are not yet measurable (video not live or no view data yet). They appear in the sheet but not in the ranking._\n")

    if deals:
        url = upload_sheet(args.brand, deals, channels, rankable)
        print(f"**Google Sheet:** {url}")
        print("Two tabs — *By Deal* (one row per sponsorship) and *By Channel* (aggregated, one row per channel).")
    else:
        print("_No deals found in this range._")


if __name__ == "__main__":
    main()
