"""Tests for `tl agent complete`: the skill reports its slug and outcome, and a
skill with no run behind it exits cleanly so the skill's own result survives."""

from unittest.mock import patch

from typer.testing import CliRunner

from tl_cli.client.errors import ApiError
from tl_cli.commands import agent as agent_mod
from tl_cli.main import app as root_app

runner = CliRunner()


class _FakeClient:
    def __init__(self, payload: dict | None = None, error: ApiError | None = None) -> None:
        self.payload = payload or {}
        self.error = error
        self.posts: list[tuple[str, dict]] = []

    def post(self, path: str, json_body: dict | None = None, timeout: float | None = None) -> dict:
        self.posts.append((path, json_body or {}))
        if self.error is not None:
            raise self.error
        return self.payload

    def close(self) -> None:
        pass


def _done() -> dict:
    return {
        "run_id": "0123456789abcdef",
        "skill": "tl-views-guarantee",
        "outcome": "completed",
        "usage": {"credits_charged": 0},
    }


def test_reports_the_skill_with_the_default_outcome() -> None:
    fake = _FakeClient(_done())
    with patch.object(agent_mod, "get_client", return_value=fake):
        result = runner.invoke(root_app, ["agent", "complete", "tl-views-guarantee", "--json"])
    assert result.exit_code == 0, result.output
    assert fake.posts == [("/agent/complete", {"skill": "tl-views-guarantee", "outcome": "completed"})]
    assert '"run_id": "0123456789abcdef"' in result.output


def test_outcome_is_passed_through() -> None:
    fake = _FakeClient(_done())
    with patch.object(agent_mod, "get_client", return_value=fake):
        result = runner.invoke(root_app, ["agent", "complete", "tl-channel-authenticity", "--outcome", "no_results"])
    assert result.exit_code == 0, result.output
    assert fake.posts[0][1] == {"skill": "tl-channel-authenticity", "outcome": "no_results"}


def test_unknown_outcome_is_refused_before_any_request() -> None:
    fake = _FakeClient(_done())
    with patch.object(agent_mod, "get_client", return_value=fake):
        result = runner.invoke(root_app, ["agent", "complete", "tl-views-guarantee", "--outcome", "done"])
    assert result.exit_code == 1
    assert fake.posts == []


def test_a_skill_started_by_hand_exits_cleanly() -> None:
    # The command sits at the end of a skill's script; a non-zero exit here would
    # read as the skill failing, when it only has nothing to report.
    error = ApiError(404, "No open run", raw={"code": "run_not_found"})
    fake = _FakeClient(error=error)
    with patch.object(agent_mod, "get_client", return_value=fake):
        result = runner.invoke(root_app, ["agent", "complete", "tl-views-guarantee"])
    assert result.exit_code == 0, result.output
    assert "No open run of tl-views-guarantee" in result.stderr


def test_other_errors_still_fail() -> None:
    error = ApiError(401, "Not signed in", raw={"code": "not_authenticated"})
    fake = _FakeClient(error=error)
    with patch.object(agent_mod, "get_client", return_value=fake), patch.object(agent_mod, "handle_api_error") as handled:
        runner.invoke(root_app, ["agent", "complete", "tl-views-guarantee"])
    handled.assert_called_once_with(error)
