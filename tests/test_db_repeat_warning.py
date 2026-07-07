"""Tests for the local repeat-query warning (`tl db` commands)."""

import json

from tl_cli import query_history
from tl_cli.commands import db
from tl_cli.query_history import note_charge, query_hash, record_and_check

# Per-run charge that crosses SPEND_THRESHOLD_CREDITS after two billed runs,
# so the standard 3rd-run warning shape still applies in tests.
_HALF_THRESHOLD = query_history.SPEND_THRESHOLD_CREDITS / 2


def _use_tmp_history(monkeypatch, tmp_path):
    monkeypatch.setattr(query_history, "HISTORY_FILE", tmp_path / "recent_queries.json")
    monkeypatch.delenv(query_history.ENV_SUPPRESS, raising=False)


def _run_billed(digest, charged=_HALF_THRESHOLD):
    """One record_and_check + post-flight charge, like a real `tl db` run."""
    due = record_and_check(digest)
    note_charge(digest, charged)
    return due


class TestQueryHash:
    def test_whitespace_and_case_collapse(self):
        assert query_hash("pg", "SELECT  1\n  FROM x;") == query_hash("pg", "select 1 from x")

    def test_engines_do_not_collide(self):
        assert query_hash("pg", "SELECT 1") != query_hash("fb", "SELECT 1")

    def test_pricing_dry_run_is_distinct(self):
        assert query_hash("pg", "SELECT 1") != query_hash("pg", "SELECT 1", pricing=True)

    def test_different_literals_are_different_queries(self):
        # Pagination (OFFSET 0/100/200) must never look like a repeat.
        assert query_hash("pg", "SELECT 1 OFFSET 0") != query_hash("pg", "SELECT 1 OFFSET 100")


class TestRecordAndCheck:
    def test_cheap_repeats_never_warn(self, monkeypatch, tmp_path):
        # The materiality floor: any number of repeats whose combined charge
        # stays under SPEND_THRESHOLD_CREDITS is silent.
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        for _ in range(10):
            assert _run_billed(digest, charged=2) is None

    def test_warns_on_third_run_once_spend_is_material(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        assert _run_billed(digest) is None
        assert _run_billed(digest) is None
        # Two billed runs at half the threshold → prior spend hits it.
        count, spent = record_and_check(digest)
        assert count == 3
        assert spent == query_history.SPEND_THRESHOLD_CREDITS

    def test_spend_just_below_threshold_is_silent(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        _run_billed(digest, charged=_HALF_THRESHOLD)
        _run_billed(digest, charged=_HALF_THRESHOLD - 1)
        assert record_and_check(digest) is None

    def test_warn_once_per_interval(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        for _ in range(3):
            _run_billed(digest)
        # 4th and 5th runs arrive while the warning is still fresh.
        assert _run_billed(digest) is None
        assert _run_billed(digest) is None

    def test_rewarns_after_interval_elapses(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        now = 1_000_000.0
        monkeypatch.setattr(query_history.time, "time", lambda: now)
        for _ in range(4):
            _run_billed(digest)
        monkeypatch.setattr(
            query_history.time, "time", lambda: now + query_history.WARN_INTERVAL_S + 1
        )
        count, spent = record_and_check(digest)
        assert count == 5
        assert spent == 4 * _HALF_THRESHOLD

    def test_runs_age_out_of_window(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        now = 1_000_000.0
        monkeypatch.setattr(query_history.time, "time", lambda: now)
        _run_billed(digest)
        _run_billed(digest)
        monkeypatch.setattr(
            query_history.time, "time", lambda: now + query_history.WINDOW_S + 1
        )
        # Both earlier runs (and their spend) expired: fresh run 1, not run 3.
        assert record_and_check(digest) is None

    def test_env_var_suppresses(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        monkeypatch.setenv(query_history.ENV_SUPPRESS, "1")
        digest = query_hash("pg", "SELECT 1")
        for _ in range(5):
            assert _run_billed(digest) is None

    def test_corrupt_state_file_is_tolerated(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        (tmp_path / "recent_queries.json").write_text("{not json", encoding="utf-8")
        digest = query_hash("pg", "SELECT 1")
        assert record_and_check(digest) is None
        # State was reset and is valid JSON again.
        state = json.loads((tmp_path / "recent_queries.json").read_text(encoding="utf-8"))
        assert digest in state

    def test_legacy_bare_timestamp_runs_are_read_as_unbilled(self, monkeypatch, tmp_path):
        # Pre-charge-tracking state files stored bare floats; they must load
        # as charge-0 runs, not crash or warn.
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        now = 1_000_000.0
        monkeypatch.setattr(query_history.time, "time", lambda: now)
        (tmp_path / "recent_queries.json").write_text(
            json.dumps({digest: {"runs": [now - 10, now - 5], "warned_at": None}}),
            encoding="utf-8",
        )
        assert record_and_check(digest) is None  # run 3, but zero spend

    def test_other_hashes_pruned_when_stale(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        now = 1_000_000.0
        monkeypatch.setattr(query_history.time, "time", lambda: now)
        record_and_check(query_hash("pg", "SELECT 1"))
        monkeypatch.setattr(
            query_history.time, "time", lambda: now + query_history.WINDOW_S + 1
        )
        record_and_check(query_hash("pg", "SELECT 2"))
        state = json.loads((tmp_path / "recent_queries.json").read_text(encoding="utf-8"))
        assert list(state) == [query_hash("pg", "SELECT 2")]


class TestNoteCharge:
    def test_bogus_and_zero_charges_ignored(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        record_and_check(digest)
        note_charge(digest, None)
        note_charge(digest, "not-a-number")
        note_charge(digest, 0)
        state = json.loads((tmp_path / "recent_queries.json").read_text(encoding="utf-8"))
        assert state[digest]["runs"][-1][1] == 0.0

    def test_charge_for_unknown_digest_is_a_noop(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        note_charge(query_hash("pg", "SELECT 1"), 50)  # nothing recorded yet


class TestWarnIfRepeat:
    def test_prints_warning_with_count_and_spend(self, monkeypatch, tmp_path, capsys):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        for _ in range(3):
            db._warn_if_repeat(digest, False)
            note_charge(digest, _HALF_THRESHOLD)
        err = " ".join(capsys.readouterr().err.split())  # undo console wrapping
        assert "Repeat query" in err
        assert "3 times" in err
        assert "1000 credits" in err
        assert "--no-repeat-warning" in err

    def test_flag_suppresses(self, monkeypatch, tmp_path, capsys):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        for _ in range(5):
            db._warn_if_repeat(digest, True)
            note_charge(digest, _HALF_THRESHOLD)
        assert "Repeat query" not in capsys.readouterr().err

    def test_silent_below_spend_threshold(self, monkeypatch, tmp_path, capsys):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        for _ in range(5):
            db._warn_if_repeat(digest, False)
            note_charge(digest, 10)
        assert "Repeat query" not in capsys.readouterr().err

    def test_silent_below_run_threshold(self, monkeypatch, tmp_path, capsys):
        _use_tmp_history(monkeypatch, tmp_path)
        db._warn_if_repeat(query_hash("pg", "SELECT 1"), False)
        db._warn_if_repeat(query_hash("pg", "SELECT 2"), False)
        assert "Repeat query" not in capsys.readouterr().err
