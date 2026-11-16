import hashlib

import pytest

from moallem.domain.canonical import canonical_hash, canonical_json, request_fingerprint
from moallem.domain.errors import NotCanonicalizable


def test_known_vector_empty_object() -> None:
    assert canonical_json({}) == "{}"
    assert canonical_hash({}) == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"


def test_keys_sorted_and_no_whitespace() -> None:
    assert canonical_json({"b": 1, "a": [True, None, "x"]}) == '{"a":[true,null,"x"],"b":1}'


def test_utf16_code_unit_key_order_not_code_point_order() -> None:
    # U+1F600 is the surrogate pair D83D DE00, so in UTF-16 order it sorts BEFORE U+FF21
    # (code-point order would put it after). Both characters are NFC-stable.
    obj = {"\uff21": "fullwidth A", "\U0001f600": "emoji", "\u20ac": "euro", "1": "one"}
    assert _keys_in_order(canonical_json(obj)) == ["1", "\u20ac", "\U0001f600", "\uff21"]


def test_nfc_runs_before_sorting_so_composition_exclusions_move() -> None:
    # RFC 8785's own vector uses U+FB33, which NFC decomposes to U+05D3 U+05BC. Under this
    # project's NFC-then-JCS pipeline it therefore sorts as U+05D3, i.e. BEFORE U+20AC.
    obj = {"\u20ac": "euro", "\ufb33": "dalet dagesh", "1": "one"}
    assert _keys_in_order(canonical_json(obj)) == ["1", "\u05d3\u05bc", "\u20ac"]


def _keys_in_order(s: str) -> list[str]:
    import json

    return list(json.loads(s).keys())


def test_nfc_equivalence_for_values_and_keys() -> None:
    composed, decomposed = "caf\u00e9", "cafe\u0301"
    assert canonical_hash({"k": composed}) == canonical_hash({"k": decomposed})
    assert canonical_hash({composed: 1}) == canonical_hash({decomposed: 1})


def test_arabic_text_is_stable_and_not_ascii_escaped() -> None:
    out = canonical_json({"q": "سؤال"})
    assert "سؤال" in out
    assert canonical_hash({"q": "سؤال"}) == hashlib.sha256(out.encode("utf-8")).hexdigest()


def test_control_characters_escaped_lowercase_hex() -> None:
    assert canonical_json('\x01\n"\\') == '"\\u0001\\n\\"\\\\"'


def test_dict_order_does_not_change_hash() -> None:
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_floats_nan_bigint_and_odd_types_rejected() -> None:
    for bad in (1.5, float("nan"), 2**53, {1: "x"}, {"a": {1, 2}}, b"x"):
        with pytest.raises(NotCanonicalizable):
            canonical_json(bad)


def test_keys_colliding_after_nfc_rejected() -> None:
    with pytest.raises(NotCanonicalizable):
        canonical_json({"caf\u00e9": 1, "cafe\u0301": 2})


def _fp(**over: object) -> str:
    base: dict[str, object] = {
        "method": "post",
        "route": "/api/v1/tasks",
        "tenant_id": "t1",
        "actor_membership_id": "m1",
        "operation_code": "CREATE_TASK",
        "payload": {"a": 1},
    }
    base.update(over)
    return request_fingerprint(**base)  # type: ignore[arg-type]


def test_fingerprint_binds_tenant_actor_operation_payload() -> None:
    assert _fp() == _fp(method="POST")
    for change in (
        {"tenant_id": "t2"},
        {"actor_membership_id": "m2"},
        {"operation_code": "X"},
        {"payload": {"a": 2}},
        {"route": "/api/v1/x"},
    ):
        assert _fp(**change) != _fp()
