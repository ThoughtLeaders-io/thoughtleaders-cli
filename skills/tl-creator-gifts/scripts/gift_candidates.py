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
import re
import sys
import urllib.parse

# tl-brand-creator-connection is installed beside this skill (skills/<name>/),
# so its folder is found from this file's own place. --profile-skill points
# elsewhere when a host installs skills in separate places.
DEFAULT_PROFILE_SKILL = pathlib.Path(__file__).resolve().parents[2] / "tl-brand-creator-connection"

# A pet is not another person: a pets fact may name the pet. Each name the
# fact lists must carry no relation word or an animal one; a person's
# relation ("wife", "friend") keeps the whole fact off a gift.
PET_WORDS = {
    "pet", "pets", "dog", "dogs", "doggo", "pup", "puppy", "puppies", "cat", "cats",
    "kitten", "kittens", "kitty", "pig", "piglet", "horse", "pony", "donkey", "bird",
    "parrot", "budgie", "chicken", "chickens", "hen", "hens", "duck", "goat", "cow",
    "sheep", "rabbit", "bunny", "hamster", "gerbil", "rat", "mouse", "ferret",
    "fish", "goldfish", "turtle", "tortoise", "lizard", "gecko", "snake", "frog",
    "axolotl", "retriever", "labrador", "lab", "poodle", "doodle", "labradoodle",
    "terrier", "bulldog", "husky", "corgi", "beagle", "dachshund", "rescue",
}


# A gift for one host reads only that host's facts. A gift for both hosts can
# start from either host's own interest (a pair gift, or one interest both
# state), from a "we" fact, and from a line the ledger knows is one of the two
# hosts without knowing which ("either").
RECIPIENT_SPEAKERS = {
    "host": {"host"},
    "cohost": {"cohost"},
    "shared": {"host", "cohost", "shared", "either"},
}


# A public figure the creator admires (a favourite author, actor, artist,
# musician) is a gift premise: a book, a print, a film poster. Every name the
# fact lists must carry one of these words in its relation, and none of the
# private words, so "favourite author" passes and "my sister, an actress" or
# "artist friend" does not.
PUBLIC_WORDS = {
    "author", "authors", "writer", "novelist", "poet", "actor", "actress", "director",
    "filmmaker", "artist", "painter", "illustrator", "musician", "singer", "songwriter",
    "band", "rapper", "composer", "comedian", "athlete", "youtuber", "streamer", "astronaut",
}
PRIVATE_WORDS = {
    "friend", "friends", "wife", "husband", "partner", "boyfriend", "girlfriend", "fiance",
    "fiancee", "ex", "mom", "mum", "mother", "dad", "father", "parent", "brother", "sister",
    "sibling", "son", "daughter", "kid", "child", "cousin", "uncle", "aunt", "grandma",
    "grandpa", "grandmother", "grandfather", "niece", "nephew", "neighbour", "neighbor",
    "colleague", "coworker", "boss", "teacher", "classmate", "roommate", "bandmate",
}


class RebuildRequired(ValueError):
    """The ledger is too old a format for gifts; only a full PROFILE rebuild fixes it."""


GIFT_DOMAINS = {"tastes", "habits", "pets", "work"}


PET_NAME_RX = re.compile(
    r"\b(?:named|called)\s+([A-Z][a-zA-Z'-]+)"
    r"|\b(?:dog|dogs|puppy|pup|cat|kitten|bunny|rabbit|horse|pony)\s+([A-Z][a-zA-Z'-]+)")


_FILLER_WORDS = {"my", "our", "her", "his", "their", "the", "a", "an", "two", "three",
                 "little", "big", "baby", "new", "old"}


def _pet_words(text):
    """The animal words in a short text ("my cats" -> ["cats"]), after filler words."""
    words = [w for w in re.sub(r"[^\w\s-]", " ", str(text or "").lower()).replace("-", " ").split()
             if w not in _FILLER_WORDS]
    return [w for w in words if w in PET_WORDS or w.rstrip("s") in PET_WORDS]


def is_pet_type(name):
    """True when a "name" is only the kind of animal ("cats", "the dog"), not a pet's name."""
    words = [w for w in re.sub(r"[^\w\s-]", " ", str(name or "").lower()).replace("-", " ").split()
             if w not in _FILLER_WORDS]
    return bool(words) and len(_pet_words(" ".join(words))) == len(words)


def claim_pet_names(fact):
    """Pet names a pets fact gives only in its claim ("has a dog named Luna"),
    for ledgers built before pet names were written into ``people``."""
    if fact.get("domain") != "pets":
        return []
    found = []
    for m in PET_NAME_RX.finditer(str(fact.get("claim") or "")):
        name = m.group(1) or m.group(2)
        if name and name not in found and not is_pet_type(name):
            found.append(name)
    return found


def pet_names(fact):
    """The pet names a fact lists, [] when it names no one, None when it names a person.
    A kind of animal ("cats") is never a name: the fact stays, the name is left out."""
    people = fact.get("people") or []
    if not people:
        return claim_pet_names(fact)
    if fact.get("domain") != "pets" or not isinstance(people, list):
        return None
    names = []
    claimed = {n.lower() for n in claim_pet_names(fact)}
    for entry in people:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"].strip():
            return None
        # "of" says the pet is someone else's ("Sam has Luna"), not the speaker's
        if entry.get("of"):
            return None
        relation = entry.get("relation")
        words = set(str(relation).lower().replace("-", " ").split()) if relation else set()
        if words and not words & PET_WORDS:
            return None
        if is_pet_type(entry["name"]):
            continue
        # a name with no relation is a pet only when the claim calls it one
        # ("a dog named Luna"); otherwise it may be a person
        if not words and entry["name"].strip().lower() not in claimed:
            return None
        names.append(entry["name"].strip())
    return names


def public_figures(fact):
    """The public figures a non-pets fact names, None when any name is not one."""
    people = fact.get("people") or []
    if not people or fact.get("domain") == "pets" or not isinstance(people, list):
        return None
    names = []
    for entry in people:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"].strip():
            return None
        relation = entry.get("relation")
        words = set(re.findall(r"[a-z]+", str(relation).lower())) if relation else set()
        if entry.get("of") or not words & PUBLIC_WORDS or words & PRIVATE_WORDS:
            return None
        names.append(entry["name"].strip())
    return names


def pet_types(fact):
    """The kinds of animal a pets fact is about ("cats", "dog"), from its people
    entries, else from its claim. Used when the pet has no name we can trust."""
    if fact.get("domain") != "pets":
        return []
    found = []
    for entry in fact.get("people") or []:
        if not isinstance(entry, dict):
            continue
        kind = _pet_words(entry.get("name")) if is_pet_type(entry.get("name")) else _pet_words(entry.get("relation"))
        found += [k for k in kind if k not in ("pet", "pets", "rescue")]
    if not found:
        found = [k for k in _pet_words(fact.get("claim")) if k not in ("pet", "pets", "rescue")]
    return list(dict.fromkeys(found))


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


# A favourite is often said once, years ago. An older fact that passes every
# other check comes back as a lasting favourite when the creator repeated it
# across different years, or stated it as lasting ("always", "favourite",
# "still"). A dated snapshot ("as of this video") or a past habit ("used to")
# never does. Pets are never lasting: a pet must be mentioned in 24 months.
LASTING_RX = re.compile(
    r"\b(always|forever|favou?rites?|obsessed|loves?|sucker for|fan of|fan\b|never wears|still)\b")
PAST_RX = re.compile(r"^\s*(as of\b|once\b|was\b|were\b|had\b)|\bused to\b", re.IGNORECASE)
LASTING_LIMIT = 15


def lasting_reason(fact):
    """Why an older fact still describes the creator, or None."""
    if fact.get("domain") == "pets":
        return None
    claim = str(fact.get("claim") or "")
    if PAST_RX.search(claim):
        return None
    first, last = date_value(fact.get("published")), date_value(fact.get("last_seen") or fact.get("seen_date"))
    recurrence = fact.get("recurrence")
    if (isinstance(recurrence, int) and recurrence >= 2 and first and last
            and first.year != last.year):
        return "repeated_across_years"
    # lower case only, so a name ("Love Lane") is not a love; a claim may
    # start with a capital ("Loves a good maxi skirt")
    if LASTING_RX.search(claim[:1].lower() + claim[1:]):
        return "stated_as_lasting"
    return None


def speaker_of(fact, multi_host):
    """Who a fact is about. Web, social and bio facts carry no speaker: on a
    one-host channel they are the host's; on a multi-host channel nobody can
    say which host, so they stay unassigned."""
    speaker = fact.get("speaker")
    if speaker is None and not multi_host and fact.get("provenance") in ("web", "social", "bio"):
        return "host"
    return speaker


def rejection(fact, as_of, recipient_role, allow_old=False, multi_host=False):
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
    # Only the kinds of fact a gift can rest on: tastes (style, collecting,
    # favourites), habits (routines, hobbies), pets, and work (their own
    # ventures, collaborations, milestones). origin, beliefs and other never do.
    if fact.get("domain") not in GIFT_DOMAINS:
        return "not_a_gift_kind"
    # A person's presence is not evidence that this recipient wants them on a
    # gift. A named pet is: pet_names() lets a pets fact through with its name.
    # So is a public figure the creator admires: public_figures() does the same.
    if pet_names(fact) is None and public_figures(fact) is None:
        return "third_party_context"
    if speaker_of(fact, multi_host) not in RECIPIENT_SPEAKERS[recipient_role]:
        return "recipient_mismatch"
    last_seen = date_value(fact.get("last_seen") or fact.get("seen_date"))
    cutoff = as_of.replace(year=as_of.year - 2, day=28) if as_of.month == 2 and as_of.day == 29 else as_of.replace(year=as_of.year - 2)
    if last_seen is None or last_seen > as_of or (not allow_old and last_seen < cutoff):
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
    multi_host = (meta or {}).get("format") == "multi_host"
    if (not meta or meta.get("schema") != "tl-creator-meta/v2"
            or meta.get("channel_id") != channel):
        raise ValueError("A published v2 PROFILE for the resolved channel is required.")
    # Ledgers built before 2026-10-05 carry the same v2 label but no speaker or
    # last_seen on their transcript facts, so every fact would fail the filter
    # and read as "no good fit". Only a full rebuild adds them; a refresh keeps
    # old facts as they are.
    if any(isinstance(fact, dict) and fact.get("provenance") == "transcript"
           and ("speaker" not in fact or "last_seen" not in fact) for fact in facts):
        raise RebuildRequired("This ledger predates 2026-10-05: rebuild it through PROFILE.")
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
    lasting = []
    fields = ("fact_id", "claim", "domain", "provenance", "quote", "video", "start",
              "url", "source_url", "source_excerpt", "published", "last_seen",
              "seen_date", "recurrence", "speaker", "speaker_name")
    for fact in facts:
        reason = ("channel_mismatch" if fact.get("provenance") == "transcript"
                  and not str(fact.get("video", "")).startswith(f"{channel}:")
                  else rejection(fact, as_of, recipient_role, multi_host=multi_host))
        why_lasting = None
        if reason == "stale_or_undated" and not rejection(fact, as_of, recipient_role, allow_old=True,
                                                          multi_host=multi_host):
            why_lasting = lasting_reason(fact)
        if why_lasting:
            candidate = {key: fact[key] for key in fields if key in fact}
            candidate["speaker"] = speaker_of(fact, multi_host)
            candidate["lasting"] = why_lasting
            figures = public_figures(fact)
            if figures:
                candidate["public_figures"] = figures
            lasting.append(candidate)
        elif reason:
            counts[reason] += 1
        else:
            candidate = {key: fact[key] for key in fields if key in fact}
            candidate["speaker"] = speaker_of(fact, multi_host)
            names = pet_names(fact)
            # a host named in a pets fact ("Sam has Luna") is a person, not a pet
            hosts = meta.get("hosts")
            host_names = {str(v).lower() for v in hosts.values()} if isinstance(hosts, dict) else set()
            names = [n for n in (names or []) if n.lower() not in host_names]
            if names:
                candidate["pet_names"] = names
            kinds = pet_types(fact)
            if kinds:
                candidate["pet_types"] = kinds
            figures = public_figures(fact)
            if figures:
                candidate["public_figures"] = figures
            accepted.append(candidate)
    context = meta.get("context") or {}
    ventures = [{"label": w.get("label"), "url": w.get("url")}
                for w in context.get("websites") or []
                if isinstance(w, dict) and public_url(w.get("url"))]
    by_speaker = collections.Counter(c.get("speaker") for c in accepted)
    # repeated-across-years first, then the most recently mentioned
    lasting.sort(key=lambda c: (c["lasting"] != "repeated_across_years",
                                -(date_value(c.get("last_seen") or c.get("seen_date")) or dt.date.min).toordinal()))
    if len(lasting) > LASTING_LIMIT:
        counts["stale_or_undated"] += len(lasting) - LASTING_LIMIT
        lasting = lasting[:LASTING_LIMIT]
    return {"schema": "tl-gift-candidates/v1", "channel_id": channel,
            "as_of": as_of.isoformat(), "recipient_role": recipient_role,
            "hosts": meta.get("hosts"),
            "candidates_by_speaker": dict(by_speaker),
            "creator_ventures": ventures,
            "status": "candidates_need_source_and_context_review" if accepted or lasting else "no_eligible_facts",
            "candidates": accepted, "lasting_favourites": lasting,
            "rejected_counts": dict(counts),
            "freshness_note": "Run PROFILE check first; this filter does not count new uploads."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-skill", type=pathlib.Path, default=DEFAULT_PROFILE_SKILL,
                        help="the tl-brand-creator-connection folder; default: the one "
                             "installed beside this skill")
    parser.add_argument("--ledger", type=pathlib.Path, required=True)
    parser.add_argument("--channel", type=int, required=True)
    parser.add_argument("--as-of", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--recipient-role", choices=("host", "cohost", "shared"), required=True)
    args = parser.parse_args(argv)
    reader = args.profile_skill / "scripts" / "store_io.py"
    if not args.profile_skill.is_absolute() or not reader.is_file():
        parser.error("tl-brand-creator-connection was not found beside this skill. Install it "
                     "(tl setup <host>) or pass its absolute folder as --profile-skill.")
    try:
        spec = importlib.util.spec_from_file_location("gift_profile_store", reader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        meta, facts = module.read_ledger(args.ledger)
        result = candidates(meta, facts, args.channel, args.as_of, args.recipient_role)
    except RebuildRequired:
        print(json.dumps({"status": "profile_rebuild_needed",
                          "reason": "This ledger was built before 2026-10-05 and lacks who said each "
                                    "fact and when it was last mentioned. Rebuild it through PROFILE "
                                    "with --rebuild (a refresh keeps the old facts), then run this "
                                    "filter again."}))
        return 2
    except (OSError, ValueError, SystemExit):
        # Reader parse errors may contain personal data; keep error output generic.
        print(json.dumps({"status": "profile_required",
                          "reason": "Invalid, missing, old or mismatched published PROFILE; rebuild or refresh through PROFILE."}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
