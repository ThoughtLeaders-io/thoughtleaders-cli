"""Tests for the prominent Hint: rendering on API errors."""

import pytest

from tl_cli.client.errors import ApiError, handle_api_error


def _render(error: ApiError, capsys) -> str:
    with pytest.raises(SystemExit) as exc:
        handle_api_error(error)
    assert exc.value.code == 1
    return " ".join(capsys.readouterr().err.split())  # undo console wrapping


class TestHintRendering:
    def test_hint_gets_its_own_line_and_is_stripped_from_detail(self, capsys):
        hint = "`reach` -> use `subscribers`. Run `tl schema pg thoughtleaders_channel` to check its columns."
        error = ApiError(
            400,
            f'column "reach" does not exist {hint}',
            raw={"detail": f'column "reach" does not exist {hint}', "hint": hint, "pgcode": "42703"},
        )
        out = _render(error, capsys)
        assert 'Error (400): column "reach" does not exist Hint:' in out
        assert out.count("`reach` -> use `subscribers`") == 1  # not duplicated

    def test_hint_not_matching_detail_suffix_still_renders(self, capsys):
        error = ApiError(400, "column x does not exist", raw={"hint": "use `y`."})
        out = _render(error, capsys)
        assert "Hint: use `y`." in out

    def test_no_hint_renders_plain_error(self, capsys):
        error = ApiError(400, 'column "reach" does not exist', raw={"pgcode": "42703"})
        out = _render(error, capsys)
        assert 'Error (400): column "reach" does not exist' in out
        assert "Hint:" not in out

    def test_missing_raw_body_is_tolerated(self, capsys):
        error = ApiError(400, "bad input", raw=None)
        assert "Error (400): bad input" in _render(error, capsys)

    def test_non_string_hint_ignored(self, capsys):
        error = ApiError(400, "bad input", raw={"hint": 42})
        out = _render(error, capsys)
        assert "Hint:" not in out
