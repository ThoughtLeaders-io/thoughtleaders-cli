#!/usr/bin/env python3
"""Filter a published creator ledger; does not verify sources or rank gifts."""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import importlib.util
import json
import math
import pathlib
import sys
import urllib.parse


def date_value(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) else None
    except (ValueError, TypeError):
        return None


def public_url(value):
    try:
        parsed = urllib.parse.urlparse(value)
        return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
    except (ValueError, TypeError, AttributeError):
        return False


def transcript_url(value, video):
    if not public_url(value):
        return False
    parsed = urllib.parse.urlparse(value)
    video_id = video.rsplit(":", 1)[-1]
    if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        return parsed.path == "/watch" and urllib.parse.parse_qs(parsed.query).get("v") == [video_id]
    return parsed.hostname == "youtu.be" and parsed.path == "/" + video_id


def rejection(fact, as_of, recipient_role):
    if not isinstance(fact.get("fact_id"), str) or not fact["fact_id"].strip():
        return "invalid_fact"
    if not isinstance(fact.get("claim"), str) or not fact["claim"].strip():
        return "invalid_fact"
    if fact.get("confidence") != "confirmed":
        return "unconfirmed"
    if any(fact.get(key) for key in
           ("ended", "superseded_by", "staged_only", "hook_only", "unverified_bio")):
        return "ineligible_history"
    if fact.get("sensitivity") not in ("none", "lifestyle") or fact.get("sensitive") is not False:
        return "sensitive_or_unclassified"
    if fact.get("domain") in ("family", "relationships", "money", "health", "home"):
        return "personal_context"
    # A person's presence is not evidence that this recipient wants them on a gift.
    if fact.get("people"):
        return "third_party_context"
    if fact.get("speaker") != recipient_role:
        return "recipient_mismatch"
    last_seen = date_value(fact.get("last_seen") or fact.get("seen_date"))
    cutoff = as_of.replace(year=as_of.year - 2, day=28) if as_of.month == 2 and as_of.day == 29 else as_of.replace(year=as_of.year - 2)
    if last_seen is None or not cutoff <= last_seen <= as_of:
        return "stale_or_undated"
    published = date_value(fact.get("published"))
    if "published" in fact and (published is None or published > last_seen):
        return "invalid_source_date"
    provenance = fact.get("provenance")
    if provenance == "transcript":
        start = fact.get("start")
        if (not isinstance(start, (int, float)) or isinstance(start, bool)
                or not math.isfinite(start) or start < 0
                or not isinstance(fact.get("quote"), str) or not fact["quote"].strip()
                or not isinstance(fact.get("video"), str) or not fact["video"]
                or not transcript_url(fact.get("url"), fact["video"])):
            return "missing_source"
        # The official writer strips verify; never demand it in a published ledger.
        if "verify" in fact and (not isinstance(fact["verify"], dict)
                                  or fact["verify"].get("match") != "exact"):
            return "unverified_source"
    elif provenance in ("web", "social", "bio"):
        if not public_url(fact.get("source_url")):
            return "missing_source"
        if provenance == "bio" and not fact.get("corroborated_by"):
            return "unverified_source"
    else:
        return "unknown_provenance"
    return None


def candidates(meta, facts, channel, as_of, recipient_role):
    if (not meta or meta.get("schema") != "tl-creator-meta/v2"
            or meta.get("channel_id") != channel):
        raise ValueError("A published v2 PROFILE for the resolved channel is required.")
    generated = date_value(meta.get("generated_at"))
    if generated is None or not 0 <= (as_of - generated).days <= 60:
        raise ValueError("Run PROFILE's freshness check and refresh this ledger.")
    if meta.get("format") not in ("solo", "interview", "multi_host", "faceless_scripted"):
        raise ValueError("PROFILE must establish the channel format first.")
    ids = [fact.get("fact_id") for fact in facts]
    if any(not isinstance(ident, str) for ident in ids) or len(set(ids)) != len(ids):
        raise ValueError("PROFILE contains invalid or duplicate fact identifiers.")
    counts = collections.Counter()
    accepted = []
    fields = ("fact_id", "claim", "domain", "provenance", "quote", "video", "start",
              "url", "source_url", "source_excerpt", "published", "last_seen",
              "seen_date", "recurrence", "speaker")
    for fact in facts:
        reason = ("channel_mismatch" if fact.get("provenance") == "transcript"
                  and not str(fact.get("video", "")).startswith(f"{channel}:")
                  else rejection(fact, as_of, recipient_role))
        if reason:
            counts[reason] += 1
        else:
            accepted.append({key: fact[key] for key in fields if key in fact})
    return {"schema": "tl-gift-candidates/v1", "channel_id": channel,
            "as_of": as_of.isoformat(), "recipient_role": recipient_role,
            "status": "candidates_need_source_and_context_review" if accepted else "no_eligible_facts",
            "candidates": accepted, "rejected_counts": dict(counts),
            "freshness_note": "Run PROFILE check first; this filter does not count new uploads."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-skill", type=pathlib.Path, required=True)
    parser.add_argument("--ledger", type=pathlib.Path, required=True)
    parser.add_argument("--channel", type=int, required=True)
    parser.add_argument("--as-of", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--recipient-role", choices=("host", "cohost", "shared"), required=True)
    args = parser.parse_args(argv)
    reader = args.profile_skill / "scripts" / "store_io.py"
    if not args.profile_skill.is_absolute() or not reader.is_file():
        parser.error("Pass the absolute installed tl-brand-creator-connection skill directory.")
    try:
        spec = importlib.util.spec_from_file_location("gift_profile_store", reader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        meta, facts = module.read_ledger(args.ledger)
        result = candidates(meta, facts, args.channel, args.as_of, args.recipient_role)
    except (OSError, ValueError, SystemExit):
        # Reader parse errors may contain personal data; keep error output generic.
        print(json.dumps({"status": "profile_required",
                          "reason": "Invalid, missing, old or mismatched published PROFILE; rebuild or refresh through PROFILE."}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
