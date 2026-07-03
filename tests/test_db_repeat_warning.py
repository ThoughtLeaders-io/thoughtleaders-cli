"""Tests for the local repeat-query warning (`tl db` commands)."""

import json

from tl_cli import query_history
from tl_cli.commands import db
from tl_cli.query_history import query_hash, record_and_check


def _use_tmp_history(monkeypatch, tmp_path):
    monkeypatch.setattr(query_history, "HISTORY_FILE", tmp_path / "recent_queries.json")
    monkeypatch.delenv(query_history.ENV_SUPPRESS, raising=False)


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
    def test_warns_on_third_run_only(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        assert record_and_check(digest) is None
        assert record_and_check(digest) is None
        assert record_and_check(digest) == 3

    def test_warn_once_per_interval(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        for _ in range(3):
            record_and_check(digest)
        # 4th and 5th runs arrive while the warning is still fresh.
        assert record_and_check(digest) is None
        assert record_and_check(digest) is None

    def test_rewarns_after_interval_elapses(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        now = 1_000_000.0
        monkeypatch.setattr(query_history.time, "time", lambda: now)
        for _ in range(4):
            record_and_check(digest)
        monkeypatch.setattr(
            query_history.time, "time", lambda: now + query_history.WARN_INTERVAL_S + 1
        )
        assert record_and_check(digest) == 5

    def test_runs_age_out_of_window(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        digest = query_hash("pg", "SELECT 1")
        now = 1_000_000.0
        monkeypatch.setattr(query_history.time, "time", lambda: now)
        record_and_check(digest)
        record_and_check(digest)
        monkeypatch.setattr(
            query_history.time, "time", lambda: now + query_history.WINDOW_S + 1
        )
        # Both earlier runs expired: this is a fresh run 1, not run 3.
        assert record_and_check(digest) is None

    def test_env_var_suppresses(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        monkeypatch.setenv(query_history.ENV_SUPPRESS, "1")
        digest = query_hash("pg", "SELECT 1")
        for _ in range(5):
            assert record_and_check(digest) is None

    def test_corrupt_state_file_is_tolerated(self, monkeypatch, tmp_path):
        _use_tmp_history(monkeypatch, tmp_path)
        (tmp_path / "recent_queries.json").write_text("{not json", encoding="utf-8")
        digest = query_hash("pg", "SELECT 1")
        assert record_and_check(digest) is None
        # State was reset and is valid JSON again.
        state = json.loads((tmp_path / "recent_queries.json").read_text(encoding="utf-8"))
        assert digest in state

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


class TestWarnIfRepeat:
    def test_prints_warning_on_third_run(self, monkeypatch, tmp_path, capsys):
        _use_tmp_history(monkeypatch, tmp_path)
        for _ in range(3):
            db._warn_if_repeat("pg", "SELECT 1", False, False)
        err = capsys.readouterr().err
        assert "Repeat query" in err
        assert "3 times" in err
        assert "--no-repeat-warning" in err

    def test_flag_suppresses(self, monkeypatch, tmp_path, capsys):
        _use_tmp_history(monkeypatch, tmp_path)
        for _ in range(5):
            db._warn_if_repeat("pg", "SELECT 1", False, True)
        assert "Repeat query" not in capsys.readouterr().err

    def test_silent_below_threshold(self, monkeypatch, tmp_path, capsys):
        _use_tmp_history(monkeypatch, tmp_path)
        db._warn_if_repeat("pg", "SELECT 1", False, False)
        db._warn_if_repeat("pg", "SELECT 2", False, False)
        assert "Repeat query" not in capsys.readouterr().err
