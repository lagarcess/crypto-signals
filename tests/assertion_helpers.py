import json
from typing import Any, Dict


def assert_dicts_equal(
    actual: Dict[str, Any], expected: Dict[str, Any], context_msg: str = ""
) -> None:
    """
    Asserts that two dictionaries are equal, providing a helpful error message with diff.
    """
    assert actual == expected, context_msg


def assert_payload_matches(
    actual: Dict[str, Any], expected_subset: Dict[str, Any], context_msg: str = ""
) -> None:
    """
    Asserts that expected_subset is a subset of actual dictionary.
    """
    missing_or_mismatch = {}
    for k, v in expected_subset.items():
        if k not in actual:
            missing_or_mismatch[k] = "MISSING"
        elif actual[k] != v:
            missing_or_mismatch[k] = {"expected": v, "actual": actual[k]}

    if missing_or_mismatch:
        error_msg = f"{context_msg}\nPayload mismatch.\nErrors: {json.dumps(missing_or_mismatch, indent=2)}\nFull Actual: {json.dumps(actual, default=str, indent=2)}"
        raise AssertionError(error_msg)
