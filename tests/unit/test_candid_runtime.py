import pytest

from pyre.candid import CandidEncodeError, MethodSpec, ServiceSpec, TypeSpec


def test_nested_validation_and_integer_bounds():
    account = TypeSpec.record({
        "owner": TypeSpec("principal"),
        "subaccount": TypeSpec.opt(TypeSpec("blob")),
    })
    account.validate({"owner": "aaaaa-aa", "subaccount": None})
    with pytest.raises(CandidEncodeError, match="unknown fields"):
        account.validate({"owner": "aaaaa-aa", "extra": 1})
    with pytest.raises(CandidEncodeError, match="outside nat8 bounds"):
        TypeSpec("nat8").validate(256)


def test_variant_shape_vector_and_method_arity():
    result = TypeSpec.variant({"ok": TypeSpec("text"), "err": TypeSpec("nat")})
    result.validate({"ok": "yes"})
    with pytest.raises(CandidEncodeError, match="exactly one"):
        result.validate({"ok": "yes", "err": 1})
    TypeSpec.vec(TypeSpec("nat8")).validate(b"bytes")
    method = MethodSpec("set", (TypeSpec("nat64"),), ())
    with pytest.raises(CandidEncodeError, match="expects 1"):
        method.validate_args(())


def test_service_methods_have_deterministic_order():
    service = ServiceSpec([
        MethodSpec("z"), MethodSpec("a", mode="query")
    ], name="Counter")
    assert [name for name, _ in service.methods] == ["a", "z"]
    assert service.method("a").mode == "query"
