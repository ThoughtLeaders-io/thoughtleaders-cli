# Comment patterns

The generic-template phrase library and handle regexes used by
`comment_analyzer.py`. Extend as new padding patterns show up; keep the code
list (`GENERIC` in `comment_analyzer.py`) and this doc in sync.

## Generic-template phrases (case-insensitive substring/exact)

```
nice video, great video, great content, thanks for sharing, first,
love this, love it, keep it up, keep going, awesome, amazing, good job,
well done, very nice, so good, best video, informative, helpful,
thank you so much, wow, super, 👍, 🔥, ❤, great work, nice one,
good video, very helpful, excellent
```

A comment counts as generic if its lowercased, punctuation-stripped form is
exactly one of these OR is ≤25 chars and contains one. Lone emoji strings are
caught separately by the emoji-only check.

## Bot-handle regex

- `^@?[a-z]+[-_]?[0-9]{4,}$` — letters then 4+ digits (YouTube
  auto-suffix style, e.g. `@viewer8821`, `@john_doe4417`). High-signal in bulk.

> Note: YouTube now appends short suffixes to many *real* handles too, so
> bot-handle share is a **supporting** signal (penalty 15), never decisive on
> its own. The decisive comment signals are scarcity and LLM-not-organic.

## Language

Channel `language == 'en'`: a comment "matches" if ≥60% of its alphabetic
chars are ASCII letters. Emoji/number-only comments are excluded from the
denominator (handled by emoji-only / length checks instead). For non-English
channels the language check is skipped (we lack reliable per-language
baselines — revisit if we onboard many non-en channels).

## What good looks like (contrast)

Real audiences on a tech channel reference specifics ("the 72→82 jump
convinced me", "where is part 1 and 2a?"), ask operational questions, argue,
and reply to each other. Padding is short, vague, off-language, emoji-heavy,
or planted product mentions ("X was built specifically for…", "signed up just
now with the launch code"). The Haiku classifier exists to catch the planted-
promotional class that keyword rules miss.
