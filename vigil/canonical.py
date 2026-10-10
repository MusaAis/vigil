"""Canonical JSON + hashing (SPEC 2.4). No floats, ever."""
from __future__ import annotations

import hashlib
import json
from typing import Any

MAX_INT = 2**53


class CanonicalError(ValueError):
    """Raised when a value cannot be canonically serialized (floats, NaN, huge ints, ...)."""


def _check(obj: Any, path: str = "$") -> None:
    if obj is None or isinstance(obj, (str, bool)):  # bool before int: bool subclasses int
        return
    if isinstance(obj, int):
        if abs(obj) > MAX_INT:
            raise CanonicalError(f"integer out of range at {path}")
        return
    if isinstance(obj, float):
        raise CanonicalError(f"float not allowed at {path}")
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _check(v, f"{path}[{i}]")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise CanonicalError(f"non-string key at {path}")
            _check(v, f"{path}.{k}")
        return
    raise CanonicalError(f"unsupported type {type(obj).__name__} at {path}")


def canonical_json(obj: Any) -> str:
    _check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(obj: Any) -> str:
    """'sha256:<hex>' of the canonical JSON of obj (used for args_sha256, digests, entry hashes)."""
    return sha256_text(canonical_json(obj))


GENESIS_HASH = sha256_text("vigil-genesis")
