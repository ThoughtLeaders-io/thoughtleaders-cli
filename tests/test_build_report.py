"""Tests for the tl-keyword-research build_report.py script (pure, no ES)."""
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest

_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills" / "tl-keyword-research" / "scripts" / "build_report.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("kw_build_report", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


br = _load()


class TestPrune:
    def test_drops_subset_keeps_broader(self):
        groups = [{"text": "tiktok shop"}, {"text": "tiktok shop affiliate"}, {"text": "selling on tiktok"}]
        kept, pruned = br.prune_redundant(groups, "OR")
        texts = [g["text"] for g in kept]
        assert "tiktok shop" in texts
        assert "tiktok shop affiliate" not in texts        # subset of "tiktok shop"
        assert pruned == [{"text": "tiktok shop affiliate", "redundant_with": "tiktok shop"}]

    def test_excludes_never_pruned(self):
        groups = [{"text": "tiktok shop"}, {"text": "tiktok shop scam", "exclude": True}]
        kept, pruned = br.prune_redundant(groups, "OR")
        assert pruned == []
        assert len(kept) == 2

    def test_no_prune_under_and(self):
        groups = [{"text": "tiktok shop"}, {"text": "tiktok shop affiliate"}]
        kept, pruned = br.prune_redundant(groups, "AND")
        assert pruned == []
        assert len(kept) == 2

    def test_boolean_or_group_not_pruned(self):
        # ("tiktok shop" | dropshipping) flattens to the same tokens as the plain
        # phrase "tiktok shop", but its `|` arm adds all the dropshipping docs —
        # pruning it would silently lose them. It must survive.
        groups = [{"text": "tiktok shop"},
                  {"text": '("tiktok shop" | dropshipping) -scam'}]
        kept, pruned = br.prune_redundant(groups, "OR")
        assert pruned == []
        assert [g["text"] for g in kept] == [
            "tiktok shop", '("tiktok shop" | dropshipping) -scam']

    def test_denoised_group_not_pruned(self):
        # The de-noised family (... -ketogene -keto) must not be pruned in favour
        # of the noisy one — the `-` exclusions it carries would be discarded.
        groups = [{"text": '("mythos 5" | mythos5)'},
                  {"text": '("mythos 5" | mythos5) -ketogene -keto'}]
        kept, pruned = br.prune_redundant(groups, "OR")
        assert pruned == []
        assert len(kept) == 2

    def test_boolean_group_does_not_prune_a_plain_phrase(self):
        # A boolean group's tokens may contain a plain phrase's tokens, but it is
        # opaque and must never act as the "broader" pruner.
        groups = [{"text": "(painting)"}, {"text": "oil painting"}]
        kept, pruned = br.prune_redundant(groups, "OR")
        assert pruned == []
        assert len(kept) == 2

    def test_hyphenated_term_treated_as_opaque(self):
        # A hyphen makes the text a potential SQS negation, so the pruner leaves
        # it alone (safe: a missed optimization, never a wrong prune).
        groups = [{"text": "art"}, {"text": "state-of-the-art"}]
        kept, pruned = br.prune_redundant(groups, "OR")
        assert pruned == []
        assert len(kept) == 2

    def test_plain_phrase_pruning_still_works(self):
        # Regression: the valid plain-vs-plain prune is unchanged.
        groups = [{"text": "retirement"}, {"text": "retirement planning"}]
        kept, pruned = br.prune_redundant(groups, "OR")
        assert [g["text"] for g in kept] == ["retirement"]
        assert pruned == [{"text": "retirement planning", "redundant_with": "retirement"}]


class TestIsBooleanGroup:
    def test_plain_phrases_are_not_boolean(self):
        for t in ["tiktok shop", "art history", "claude fable 5", "fable5", "401k"]:
            assert br.is_boolean_group(t) is False, t

    def test_operator_bearing_text_is_boolean(self):
        for t in ['("a" | b)', "a -b", "retire*", '"a b"~2', "a + b", "(x)"]:
            assert br.is_boolean_group(t) is True, t


class TestFilterSet:
    def test_maps_are_positional_lists(self):
        # The platform stores per-keyword maps as LISTS indexed by position
        # (null / false = defaults) — the shape the web app saves. A dict here
        # breaks every server-side read of the saved report.
        groups = [
            {"text": "tiktok shop"},
            {"text": "selling", "content_fields": ["title"]},
            {"text": "scam", "exclude": True},
        ]
        fs = br.build_filter_set(groups, "OR", ["title", "summary", "transcript"])
        assert fs["keywords"] == ["tiktok shop", "selling", "scam"]
        assert fs["keyword_operator"] == "OR"
        assert fs["keyword_content_fields_map"] == [None, ["title"], None]
        assert fs["keyword_exclude_map"] == [False, False, True]

    def test_maps_always_emitted_full_length(self):
        # Even all-default keywords carry full-length maps: a truthy
        # content-fields map is what keeps a saved report from re-deriving a
        # legacy combined-content filter on top of the keyword groups.
        fs = br.build_filter_set([{"text": "a"}, {"text": "b"}], "OR", ["title"])
        assert fs["keyword_content_fields_map"] == [None, None]
        assert fs["keyword_exclude_map"] == [False, False]


class TestInlineLink:
    def test_link_roundtrips_keyword_groups(self):
        groups = [{"text": "tiktok shop"}, {"text": "scam", "exclude": True}]
        url = br.build_inline_link(groups, "OR", "thoughtleaders", ["title", "summary"], br.DEFAULT_APP_URL)
        parsed = urlparse(url)
        assert parsed.path == "/"
        # hash route + query live in the fragment
        frag = url.split("#/", 1)[1]
        slug, query = frag.split("?", 1)
        assert slug == "thoughtleaders"
        qs = parse_qs(query)
        assert qs["term_operator"] == ["OR"]
        kg = json.loads(unquote(qs["keyword_groups"][0]))
        assert kg == [{"text": "tiktok shop"}, {"text": "scam", "exclude": True}]
        assert qs["content_fields"] == ["title,summary"]


class TestMain:
    def test_end_to_end(self, monkeypatch, capsys):
        spec = {
            "operator": "OR", "report_type": "channels", "title": "TikTok Shop creators",
            "groups": [{"text": "tiktok shop"}, {"text": "tiktok shop affiliate"},
                       {"text": "dropshipping", "exclude": True}],
        }
        monkeypatch.setattr(br.sys, "argv", ["build_report.py"])
        monkeypatch.setattr(br.sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(br.sys.stdin, "read", lambda: json.dumps(spec))
        br.main()
        out = json.loads(capsys.readouterr().out)
        assert out["report_type"] == "channels"
        assert out["filter_set"]["keywords"] == ["tiktok shop", "dropshipping"]
        assert out["filter_set"]["keyword_exclude_map"] == [False, True]
        assert out["pruned"] == [{"text": "tiktok shop affiliate", "redundant_with": "tiktok shop"}]
        assert out["report_config"]["report_type"] == 3       # channels
        assert "app.thoughtleaders.io/#/thoughtleaders?" in out["report_link"]


class TestContentFieldValidation:
    def _run(self, spec, monkeypatch):
        import pytest
        monkeypatch.setattr(br.sys, "argv", ["build_report.py"])
        monkeypatch.setattr(br.sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(br.sys.stdin, "read", lambda: json.dumps(spec))
        with pytest.raises(SystemExit):
            br.main()

    def test_rejects_raw_es_path(self, monkeypatch):
        # ai.topic_descriptions is an ES path, not a ContentField enum name
        self._run({"report_type": "channels",
                   "groups": [{"text": "cooking", "content_fields": ["ai.topic_descriptions"]}]},
                  monkeypatch)

    def test_rejects_unknown_default_field(self, monkeypatch):
        self._run({"report_type": "videos", "default_content_fields": ["bogus"],
                   "groups": [{"text": "x"}]}, monkeypatch)

    def test_accepts_valid_enum_fields(self, monkeypatch, capsys):
        import pytest
        spec = {"report_type": "channels",
                "groups": [{"text": "cooking", "content_fields": ["title", "channel_topic_description"]}]}
        monkeypatch.setattr(br.sys, "argv", ["build_report.py"])
        monkeypatch.setattr(br.sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(br.sys.stdin, "read", lambda: json.dumps(spec))
        br.main()
        out = json.loads(capsys.readouterr().out)
        assert out["filter_set"]["keyword_content_fields_map"] == [["title", "channel_topic_description"]]


class TestAppSyntaxTranslation:
    """Boolean-group SQS text must ship in the web app's keyword grammar —
    uppercase AND/OR/NOT + parens + quoted atoms. Raw SQS operators are inert
    (phrase-quoted) in the app, which is exactly how report links break."""

    def test_plain_phrase_untouched(self):
        assert br.sqs_to_app_syntax("tiktok shop") == "tiktok shop"

    def test_or_group(self):
        assert (br.sqs_to_app_syntax('("fable 5" | fable5 | "fable five")')
                == '( "fable 5" OR "fable5" OR "fable five" )')

    def test_in_group_exclusion_becomes_and_not(self):
        assert (br.sqs_to_app_syntax('("mythos 5" | mythos5) -ketogene -keto')
                == '( "mythos 5" OR "mythos5" ) AND NOT "ketogene" AND NOT "keto"')

    def test_and_anchor_pattern(self):
        got = br.sqs_to_app_syntax(
            'cannes +lions +(advertising | agency | "young lions") -"film festival"')
        assert got == ('"cannes" AND "lions" AND ( "advertising" OR "agency" OR '
                       '"young lions" ) AND NOT "film festival"')

    def test_arm_scoped_exclusion_preserved(self):
        got = br.sqs_to_app_syntax('("fable 5" | ("anthropic banned" -openclaw))')
        assert got == '( "fable 5" OR ( "anthropic banned" AND NOT "openclaw" ) )'

    def test_negated_group(self):
        assert br.sqs_to_app_syntax("-(sermon | gospel)") == 'NOT ( "sermon" OR "gospel" )'

    def test_implicit_adjacency_becomes_explicit_and(self):
        # probe --mode sqs runs with default_operator=and; the app has no such
        # default, so bare adjacency must be spelled out.
        assert br.sqs_to_app_syntax("cannes +lions") == '"cannes" AND "lions"'

    def test_prefix_operator_rejected(self):
        with pytest.raises(ValueError):
            br.sqs_to_app_syntax("retire* | pension")

    def test_slop_rejected(self):
        with pytest.raises(ValueError):
            br.sqs_to_app_syntax('"retirement planning"~2')

    def test_operators_inside_quotes_stay_literal(self):
        assert br.sqs_to_app_syntax('("a~b" | c)') == '( "a~b" OR "c" )'


class TestTranslationInDeliverable:
    def _run(self, spec, monkeypatch, capsys):
        monkeypatch.setattr(br.sys, "argv", ["build_report.py"])
        monkeypatch.setattr(br.sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(br.sys.stdin, "read", lambda: json.dumps(spec))
        br.main()
        return json.loads(capsys.readouterr().out)

    def test_boolean_group_translated_everywhere(self, monkeypatch, capsys):
        spec = {"operator": "OR", "report_type": "channels",
                "groups": [{"text": '("mythos 5" | mythos5) -keto'},
                           {"text": "fable 5"}]}
        out = self._run(spec, monkeypatch, capsys)
        translated = '( "mythos 5" OR "mythos5" ) AND NOT "keto"'
        assert translated in out["filter_set"]["keywords"]
        assert "fable 5" in out["filter_set"]["keywords"]
        assert out["translated"] == [
            {"from": '("mythos 5" | mythos5) -keto', "to": translated}]
        # the link carries the translated text (JSON inside the URL), never raw SQS
        link_qs = parse_qs(urlparse(out["report_link"]).fragment.split("?", 1)[1])
        link_groups = json.loads(link_qs["keyword_groups"][0])
        assert [g["text"] for g in link_groups] == [translated, "fable 5"]
        # report_config mirrors the filter_set
        assert translated in out["report_config"]["filterset"]["keywords"]

    def test_expression_rendered(self, monkeypatch, capsys):
        spec = {"operator": "OR", "report_type": "channels",
                "groups": [{"text": "fable 5"},
                           {"text": "claude mythos"},
                           {"text": "dropshipping", "exclude": True}]}
        out = self._run(spec, monkeypatch, capsys)
        assert out["expression"] == "(fable 5) OR (claude mythos) AND NOT dropshipping"

    def test_unsupported_operator_fails_loudly(self, monkeypatch, capsys):
        spec = {"operator": "OR", "report_type": "channels",
                "groups": [{"text": "retire* planning"}]}
        monkeypatch.setattr(br.sys, "argv", ["build_report.py"])
        monkeypatch.setattr(br.sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(br.sys.stdin, "read", lambda: json.dumps(spec))
        with pytest.raises(SystemExit) as exc:
            br.main()
        assert "prefix" in str(exc.value)


class TestTranslationSemanticsGuards:
    """Fixes from the adversarial review: plain phrases with in-word signs pass
    through untouched; detached '-' and escapes fail loudly; operator words in
    plain phrases are quoted; detached '+' is the infix AND."""

    def test_in_word_hyphen_phrases_pass_through(self):
        # probed as an adjacent phrase; must ship as the same phrase, never
        # be rewritten into an AND of separate terms (silent broadening)
        for text in ["e-commerce marketing", "covid-19 vaccine",
                     "t-shirt printing", "disney+ shows", "3-day split"]:
            assert br.sqs_to_app_syntax(text) == text, text

    def test_in_word_hyphen_inside_group_stays_whole(self):
        assert (br.sqs_to_app_syntax('(e-commerce | ecommerce)')
                == '( "e-commerce" OR "ecommerce" )')

    def test_detached_minus_rejected(self):
        # SQS drops a '-' followed by whitespace, so the probe measured the
        # term REQUIRED; shipping it as an exclusion would invert semantics.
        with pytest.raises(ValueError):
            br.sqs_to_app_syntax("(crypto | bitcoin) - scam")
        with pytest.raises(ValueError):
            br.sqs_to_app_syntax("(crypto) -")

    def test_detached_plus_is_infix_and(self):
        assert br.sqs_to_app_syntax("(a | b) + c") == '( "a" OR "b" ) AND "c"'

    def test_backslash_escape_rejected(self):
        with pytest.raises(ValueError):
            br.sqs_to_app_syntax('("32\\" tv" | television)')

    def test_operator_word_in_plain_phrase_gets_quoted(self):
        # 'rock AND roll' probed as a phrase; unquoted, AND would act as an
        # operator in the link. Whole-phrase quoting keeps it literal.
        assert br.sqs_to_app_syntax("rock AND roll") == '"rock AND roll"'
        assert br.sqs_to_app_syntax("moving to portland OR seattle") == \
            '"moving to portland OR seattle"'

    def test_operator_word_as_bare_group_term_stays_quoted_literal(self):
        assert br.sqs_to_app_syntax("(rock | AND)") == '( "rock" OR "AND" )'
