import math
import pytest
from vigil.canonical import (CanonicalError, GENESIS_HASH, MAX_INT, canonical_json, sha256_json,
                             sha256_text)


def test_sorted_keys_no_whitespace():
    assert canonical_json({"b": 1, "a": [1, 2, {"d": None, "c": True}]}) == \
        '{"a":[1,2,{"c":true,"d":null}],"b":1}'


def test_unicode_not_escaped():
    assert canonical_json({"k": "₦é"}) == '{"k":"₦é"}'


def test_bool_is_not_int():
    assert canonical_json([True, False, 1, 0]) == "[true,false,1,0]"


@pytest.mark.parametrize("bad", [1.5, 0.0, float("nan"), float("inf"), -float("inf"),
                                 {"a": 1.0}, [1, [2.5]], {"a": {"b": [3.14]}}])
def test_floats_rejected_anywhere(bad):
    with pytest.raises(CanonicalError):
        canonical_json(bad)


def test_int_range():
    assert canonical_json(MAX_INT) == str(MAX_INT)
    with pytest.raises(CanonicalError):
        canonical_json(MAX_INT + 1)
    with pytest.raises(CanonicalError):
        canonical_json(-MAX_INT - 1)


def test_non_string_keys_and_other_types_rejected():
    with pytest.raises(CanonicalError):
        canonical_json({1: "a"})
    with pytest.raises(CanonicalError):
        canonical_json({"a": {1, 2}})
    with pytest.raises(CanonicalError):
        canonical_json({"a": b"x"})


def test_key_order_does_not_change_hash():
    assert sha256_json({"a": 1, "b": 2}) == sha256_json({"b": 2, "a": 1})


def test_genesis_constant():
    assert GENESIS_HASH == sha256_text("vigil-genesis")
    assert GENESIS_HASH == \
        "sha256:847e4febfe1c429a14d7a66675ec721211b2e9487306986f7c1060f8d80766db"
    assert not math.isnan(1)  # keep math imported for the nan params above
