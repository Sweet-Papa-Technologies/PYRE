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
