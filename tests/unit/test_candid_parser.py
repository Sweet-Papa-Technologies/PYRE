import pytest

from pyre._candid_parser import CandidSyntaxError, parse


DID = """
type Account = record { owner : principal; subaccount : opt blob };
type Result = variant { ok : nat64; err : text };
service : {
  balance : (Account) -> (nat64) query;
  transfer : (Account, nat64) -> (Result);
}
"""


def test_parse_aliases_records_variants_opts_and_modes():
    service = parse(DID)
    assert [name for name, _ in service.methods] == ["balance", "transfer"]
    assert service.method("balance").mode == "query"
    service.method("transfer").args[0].validate({"owner": "aaaaa-aa", "subaccount": None})
    service.method("transfer").returns[0].validate({"ok": 3})


def test_syntax_error_reports_location_token_and_expected():
    with pytest.raises(CandidSyntaxError) as caught:
        parse("service : { broken : (nat) (nat); }")
    error = caught.value
    assert error.line == 1 and error.column > 1
    assert error.token == "("
    assert error.expected == "->"


def test_source_and_nesting_limits():
    with pytest.raises(ValueError, match="nesting"):
        parse("service : { x : (opt opt opt nat) -> (); }", max_depth=1)
    with pytest.raises(ValueError, match="source exceeds"):
        parse("service : {}", max_source_bytes=5)


def test_forward_aliases_resolve_and_recursive_aliases_fail_closed():
    service = parse("type A = B; type B = record { value : nat }; service : { get : () -> (A) }")
    service.method("get").returns[0].validate({"value": 1})
    with pytest.raises(ValueError, match="recursive alias cycle"):
        parse("type A = opt B; type B = vec A; service : { get : () -> (A) }")
    with pytest.raises(ValueError, match="unknown Candid type alias"):
        parse("service : { get : () -> (Missing) }")


def test_alias_fan_out_resolves_in_linear_time():
    # regression: a record whose two fields both reference the next alias used
    # to expand as O(2^n) structural duplication and hang on a tiny input.
    # (Do not repr/validate the resolved type here: memoization makes it a
    # shared-subtree graph whose naive repr is itself exponential.)
    import time
    lines = ["type A%d = record { a: A%d; b: A%d };" % (i, i + 1, i + 1) for i in range(40)]
    lines.append("type A40 = nat;")
    lines.append("service : { ping: (A0) -> (nat) };")
    started = time.time()
    service = parse("\n".join(lines))
    elapsed = time.time() - started
    names = [name for name, _ in service.methods]
    assert names == ["ping"]
    assert elapsed < 2.0


def test_deep_alias_nesting_raises_candid_error_not_recursionerror():
    lines = ["type A%d = %sA%d;" % (i, "opt " * 40, i + 1) for i in range(60)]
    lines.append("type A60 = nat;")
    lines.append("service : { ping: (A0) -> (nat) };")
    try:
        parse("\n".join(lines))
        raised = None
    except RecursionError as exc:  # pragma: no cover - would be the bug
        raised = exc
    except ValueError as exc:
        raised = exc
    assert isinstance(raised, ValueError) and not isinstance(raised, RecursionError)
