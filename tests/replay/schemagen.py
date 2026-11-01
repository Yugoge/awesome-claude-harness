"""Schema-valid instances from the JSON Schemas of the tree under test.

A simulated subagent writes each JSON artifact its obligation declares from the
schema the obligation names (schemas/<id>.json of the tree under test), never
from a hand-written field list: instance() builds the smallest instance that
validates (required properties, the first enum value or const, the first
oneOf/anyOf branch, minItems items, minLength strings, a pattern-matching
string, a date-time for format date-time), deep-merges the caller's content
over it, and then satisfies allOf's if/then and not-required clauses. valid()
checks the result with jsonschema when the venv has it.

Draft-07 subset: the schemas under schemas/ use nothing else. An unsupported
construct raises, so a schema change fails the driver loudly.
"""
from __future__ import annotations

import copy
import json
import os
import random
import re
import time

try:  # the harness venv carries jsonschema (requirements.txt); validation is skipped without it
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover
    jsonschema = None


class SchemaError(ValueError):
    pass


def load(harness: str, schema_id: str) -> dict:
    """The schema registered under `schema_id` (schemas/registry.json), else schemas/<id>.json."""
    sdir = os.path.join(harness, "schemas")
    name = schema_id + ".json"
    try:
        with open(os.path.join(sdir, "registry.json")) as fh:
            name = (json.load(fh).get("schemas") or {}).get(schema_id, name)
    except (OSError, ValueError):
        pass
    with open(os.path.join(sdir, name)) as fh:
        return json.load(fh)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------- regex sampler

try:  # Python 3.11+
    import re._parser as _sre  # type: ignore
    from re._constants import (ANY, AT, BRANCH, CATEGORY, IN, LITERAL, MAX_REPEAT, MIN_REPEAT,  # type: ignore
                               NEGATE, NOT_LITERAL, RANGE, SUBPATTERN)
except ImportError:  # pragma: no cover
    import sre_parse as _sre  # type: ignore
    from sre_constants import (ANY, AT, BRANCH, CATEGORY, IN, LITERAL, MAX_REPEAT, MIN_REPEAT,  # type: ignore
                               NEGATE, NOT_LITERAL, RANGE, SUBPATTERN)

_CATEGORY_CHARS = {"CATEGORY_DIGIT": "0123456789", "CATEGORY_WORD": "abcxyz0123_", "CATEGORY_SPACE": " ",
                   "CATEGORY_NOT_DIGIT": "abc", "CATEGORY_NOT_WORD": "-.", "CATEGORY_NOT_SPACE": "abc"}


def _in_chars(items) -> list[str]:
    out, neg = [], False
    for op, av in items:
        if op is NEGATE:
            neg = True
        elif op is LITERAL:
            out.append(chr(av))
        elif op is RANGE:
            out.extend(chr(x) for x in range(av[0], av[1] + 1))
        elif op is CATEGORY:
            out.extend(_CATEGORY_CHARS.get(str(av), "a"))
    if neg:
        return [c for c in "abcdefghijklmnopqrstuvwxyz0123456789" if c not in out]
    return out


def _emit(parsed, rng: random.Random, hint: int) -> str:
    out = []
    for op, av in parsed:
        if op is LITERAL:
            out.append(chr(av))
        elif op is NOT_LITERAL:
            out.append("a" if chr(av) != "a" else "b")
        elif op is ANY:
            out.append("a")
        elif op is IN:
            out.append(rng.choice(_in_chars(av)))
        elif op is CATEGORY:
            out.append(rng.choice(_CATEGORY_CHARS.get(str(av), "a")))
        elif op in (MAX_REPEAT, MIN_REPEAT):
            lo, hi, sub = av
            n = lo if hi == lo else max(lo, min(hi, hint))
            out.extend(_emit(sub, rng, hint) for _ in range(n))
        elif op is SUBPATTERN:
            out.append(_emit(av[-1], rng, hint))
        elif op is BRANCH:
            out.append(_emit(av[1][0], rng, hint))
        elif op is AT:
            continue
        else:
            raise SchemaError(f"unsupported regex construct {op}")
    return "".join(out)


def sample_pattern(pattern: str, rng: random.Random, length_hint: int = 8) -> str:
    """A string matching `pattern`: the first branch of each alternation, `length_hint` repeats."""
    s = _emit(_sre.parse(pattern), rng, length_hint)
    if not re.search(pattern, s):
        raise SchemaError(f"could not sample a string for pattern {pattern!r}")
    return s


# ---------------------------------------------------------------- instance generation

class Gen:
    def __init__(self, root: dict, seed: str = ""):
        self.root = root
        self.rng = random.Random(seed or root.get("$id", ""))

    def resolve(self, s: dict) -> dict:
        while isinstance(s, dict) and "$ref" in s:
            ref = s["$ref"]
            if not ref.startswith("#/"):
                raise SchemaError(f"non-local $ref {ref!r}")
            node = self.root
            for part in ref[2:].split("/"):
                node = node[part]
            s = node
        return s

    def make(self, s: dict, name: str = "value", given=None):
        s = self.resolve(s)
        if given is not None:
            return self.fill(s, given, name)
        if "const" in s:
            return copy.deepcopy(s["const"])
        if "enum" in s:
            return copy.deepcopy(s["enum"][0])
        for key in ("oneOf", "anyOf"):
            if key in s:
                return self.make(s[key][0], name)
        t = s.get("type")
        if isinstance(t, list):
            t = next((x for x in t if x != "null"), t[0])
        if t is None:
            t = "object" if "properties" in s or "required" in s else "string"
        if t == "object":
            return self.fill(s, {}, name)
        if t == "array":
            n = int(s.get("minItems") or 0)
            items = s.get("items") or {}
            return [self.make(items, f"{name}-{k + 1}") for k in range(n)]
        if t == "string":
            return self.string(s, name)
        if t == "integer":
            return int(s.get("minimum", 0))
        if t == "number":
            return s.get("minimum", 0)
        if t == "boolean":
            return False
        if t == "null":
            return None
        raise SchemaError(f"unsupported type {t!r}")

    def string(self, s: dict, name: str) -> str:
        if s.get("format") == "date-time":
            return now_iso()
        if "pattern" in s:
            text = f"replay {name}"
            return text if re.search(s["pattern"], text) else sample_pattern(s["pattern"], self.rng)
        text = f"replay {name}"
        return text.ljust(int(s.get("minLength") or 0), ".")

    def fill(self, s: dict, given, name: str):
        """`given` completed to satisfy `s` (objects gain their required properties)."""
        s = self.resolve(s)
        if not isinstance(given, dict) or not isinstance(s, dict):
            return given
        props = s.get("properties") or {}
        out = {}
        for k, v in given.items():
            out[k] = self.fill(props[k], v, k) if k in props else v
        for k in s.get("required") or []:
            if k not in out:
                out[k] = self.make(props.get(k, {}), k)
        for k in range(int(s.get("minProperties") or 0) - len(out)):
            out[f"replay_{k + 1}"] = f"replay {name}"
        return out


def deep_merge(base, over):
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = deep_merge(base.get(k), v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(over)


def set_path(doc: dict, dotted: str, value) -> None:
    node = doc
    parts = dotted.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def get_path(doc, dotted: str):
    node = doc
    for p in dotted.split("."):
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def _matches(schema: dict, doc) -> bool:
    if jsonschema is None:
        return False
    return jsonschema.Draft7Validator(schema).is_valid(doc)


def _apply_all_of(gen: Gen, s: dict, doc):
    for sub in s.get("allOf") or []:
        sub = gen.resolve(sub)
        if "if" in sub:
            if _matches(dict(gen.resolve(sub["if"]), definitions=gen.root.get("definitions", {})), doc):
                doc = gen.fill(sub.get("then") or {}, doc, "then")
            elif "else" in sub:
                doc = gen.fill(sub["else"], doc, "else")
        elif "not" in sub and set(sub["not"]) == {"required"}:
            for k in sub["not"]["required"]:
                doc.pop(k, None)
        else:
            doc = gen.fill(sub, doc, "allOf")
    return doc


def instance(schema: dict, content: dict | None = None, seed: str = "") -> dict:
    """The minimal instance of `schema` with `content` deep-merged over it, then repaired from the
    validator's own errors (conditional and combined constraints of any depth)."""
    gen = Gen(schema, seed)
    doc = gen.make(schema, schema.get("$id", "doc"))
    if content:
        doc = gen.fill(schema, deep_merge(doc, content), schema.get("$id", "doc"))
    return repair(gen, schema, _apply_all_of(gen, schema, doc))


def _at(doc, path):
    node = doc
    for p in path:
        node = node[p]
    return node


def _put(doc, path, value):
    if not path:
        return value
    _at(doc, path[:-1])[path[-1]] = value
    return doc


def repair(gen: Gen, schema: dict, doc, rounds: int = 40):
    """Fix what the validator reports, one error at a time: a missing required property is generated,
    a const or enum takes its value, a wrong type, a too-short array or string, and an unmet
    anyOf/oneOf (its first branch) are regenerated in place. Content the caller gave is kept
    wherever it does not violate the schema."""
    if jsonschema is None:
        return doc
    validator = jsonschema.Draft7Validator(schema)
    for _ in range(rounds):
        errs = sorted(validator.iter_errors(doc), key=lambda e: (len(e.absolute_path), str(e.absolute_path)))
        if not errs:
            return doc
        e = errs[0]
        path, sub, kind = list(e.absolute_path), gen.resolve(e.schema), e.validator
        cur = _at(doc, path)
        if kind == "required":
            for name in e.validator_value:
                if isinstance(cur, dict) and name not in cur:
                    cur[name] = gen.make((sub.get("properties") or {}).get(name, {}), name)
        elif kind == "const":
            doc = _put(doc, path, copy.deepcopy(e.validator_value))
        elif kind == "enum":
            doc = _put(doc, path, copy.deepcopy(e.validator_value[0]))
        elif kind in ("type", "format", "pattern"):
            doc = _put(doc, path, gen.make(sub, str(path[-1]) if path else "doc"))
        elif kind == "minItems" and isinstance(cur, list):
            cur.extend(gen.make(sub.get("items") or {}, "item") for _ in range(e.validator_value - len(cur)))
        elif kind == "minLength" and isinstance(cur, str):
            doc = _put(doc, path, cur.ljust(e.validator_value, "."))
        elif kind in ("anyOf", "oneOf"):  # satisfy the first branch, repaired against that branch alone
            branch = gen.resolve(e.validator_value[0])
            start = gen.fill(branch, cur, "branch") if isinstance(cur, dict) else gen.make(branch, "branch")
            doc = _put(doc, path, repair(gen, dict(branch, definitions=gen.root.get("definitions", {})), start))
        elif kind == "not" and isinstance(e.validator_value, dict) and set(e.validator_value) == {"required"}:
            for name in e.validator_value["required"]:
                cur.pop(name, None)
        elif kind == "not":
            doc = _put(doc, path, f"replay {path[-1] if path else 'value'}")
        elif kind == "additionalProperties" and isinstance(cur, dict):
            allowed = set(sub.get("properties") or {})
            for name in [k for k in cur if k not in allowed]:
                cur.pop(name)
        else:
            raise SchemaError(f"cannot repair {kind} at /{'/'.join(map(str, path))}: {e.message}")
    return doc


def errors(schema: dict, doc) -> list[str]:
    """Validation errors ([] when valid, or when jsonschema is unavailable)."""
    if jsonschema is None:
        return []
    v = jsonschema.Draft7Validator(schema)
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in v.iter_errors(doc)]


def enum_paths(schema: dict, value, prefix: str = "") -> list[str]:
    """Dotted paths of `schema` whose enum holds `value` (properties only, no arrays)."""
    found = []
    for k, sub in (schema.get("properties") or {}).items():
        path = f"{prefix}{k}"
        if value in (sub.get("enum") or []):
            found.append(path)
        if isinstance(sub, dict) and sub.get("properties"):
            found.extend(enum_paths(sub, value, path + "."))
    return found
