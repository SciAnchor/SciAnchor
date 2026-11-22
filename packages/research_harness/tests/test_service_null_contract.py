"""Strict optional nulls obey the published schema; legacy compat stays explicit."""

import pytest

from research_harness.service.dispatcher import _validate_schema_value


@pytest.mark.parametrize(
    "kind", ["string", "integer", "number", "boolean", "object", "array"]
)
def test_strict_optional_absent_is_not_explicit_null(kind):
    schema = {
        "type": "object",
        "properties": {"value": {"type": kind}},
        "additionalProperties": False,
    }
    assert _validate_schema_value({}, schema, policy="strict") is None
    assert _validate_schema_value({"value": None}, schema, policy="strict") is not None
    assert _validate_schema_value({"value": None}, schema, policy="compat") is None


def test_strict_explicit_nullable_optional_remains_allowed():
    schema = {
        "type": "object",
        "properties": {"value": {"type": ["string", "null"]}},
        "additionalProperties": False,
    }
    assert _validate_schema_value({}, schema, policy="strict") is None
    assert _validate_schema_value({"value": None}, schema, policy="strict") is None
    assert _validate_schema_value({"value": "ok"}, schema, policy="strict") is None
    assert _validate_schema_value({"value": 7}, schema, policy="strict") is not None


def test_strict_optional_null_in_array_item_is_validated():
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"severity": {"type": "string", "enum": ["major", "minor"]}},
        },
    }
    assert _validate_schema_value([{}], schema, policy="strict") is None
    assert "severity" in _validate_schema_value(
        [{"severity": None}], schema, policy="strict"
    )
