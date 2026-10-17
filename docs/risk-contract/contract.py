"""Strict stdlib validator for the bounded risk-contract pilot, not all JSON Schema."""
import hashlib
import json
import re
from pathlib import Path

VERSION = "nakedagent-risk-contract/0.2.0"
MAX_BYTES = 65536
DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
ID = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[a-zA-Z0-9_.:/-]+$"}


def obj(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def array(items, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": 128,
            "uniqueItems": True}


SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Bounded nakedagent risk contract pilot 0.2.0",
    **obj({
        "schema": {"type": "string", "const": VERSION},
        "run_id": ID,
        "principal": ID,
        "policy_sha256": DIGEST,
        "configuration_sha256": DIGEST,
        "dependency_graph_sha256": DIGEST,
        "components": array(obj({"id": ID, "sha256": DIGEST,
                                 "dependencies": array(ID)}), 1),
        "grants": array(obj({"operation": ID, "resource": ID}), 1),
        "required_evidence": array(ID, 1),
        "max_actions": {"type": "integer", "minimum": 1, "maximum": 1000},
        "expires_at": {"type": "integer", "minimum": 1, "maximum": 9007199254740991},
    }),
}


def canonical(value):
    # Pilot inputs are constrained to ASCII identifiers, integers and containers.
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def loads(raw):
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        raise ValueError("contract input must be bounded UTF-8 bytes")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        validate(value)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid encoding or nesting") from exc
    return value


def _check(value, schema, path="contract"):
    kinds = {"object": dict, "array": list, "string": str, "integer": int}
    if type(value) is not kinds[schema["type"]]:
        raise ValueError(f"{path}: wrong type")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path}: unsupported constant")
    if type(value) is dict:
        if set(value) != set(schema["required"]):
            raise ValueError(f"{path}: missing or unknown fields")
        for key, item in value.items():
            _check(item, schema["properties"][key], path + "." + key)
    elif type(value) is list:
        if not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise ValueError(f"{path}: array bounds")
        for item in value:
            _check(item, schema["items"], path + "[]")
        if len({canonical(item) for item in value}) != len(value):
            raise ValueError(f"{path}: duplicate entries")
    elif type(value) is str:
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 128):
            raise ValueError(f"{path}: string bounds")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise ValueError(f"{path}: invalid identifier/digest")
    elif not schema["minimum"] <= value <= schema["maximum"]:
        raise ValueError(f"{path}: integer bounds")


def validate(contract):
    _check(contract, SCHEMA)
    ids = [c["id"] for c in contract["components"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate component identity")
    for component in contract["components"]:
        if any(d not in ids for d in component["dependencies"]):
            raise ValueError("unresolved dependency")
    if len(canonical(contract)) > MAX_BYTES:
        raise ValueError("contract too large")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    args = parser.parse_args()
    with args.contract.open("rb") as source:
        value = loads(source.read(MAX_BYTES + 1))
    print(json.dumps({"valid": True, "sha256": digest(value), "authority_granted": False}))
