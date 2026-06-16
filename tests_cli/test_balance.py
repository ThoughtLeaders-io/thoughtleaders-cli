"""Read-only: `tl balance` returns the org's credit balance."""


def test_balance_returns_numeric_balance(tl_json):
    data = tl_json("balance")
    assert "balance" in data, data
    # Balance must be a number (the CLI renders it and warns when low).
    float(data["balance"])
