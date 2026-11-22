"""Prints the public surface of the Python SDK as JSON: which contract operation each method binds and its parameters.

Run with the SDK's venv: packages/python/.venv/bin/python scripts/python_surface.py
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "python" / "src"))

import flexenai  # noqa: E402
from flexenai._base import SDK_OPTIONS  # noqa: E402
from flexenai._errors import ERROR_CLASS_BY_CODE  # noqa: E402


def walk(obj: object, prefix: str, seen: set[int], out: dict[str, dict[str, object]], flavour: str) -> None:
    if id(obj) in seen:
        return
    seen.add(id(obj))
    for name in dir(obj):
        if name.startswith("_"):
            continue
        attr = getattr(obj, name)
        op = getattr(attr, "__flexen_operation__", None)
        if op is not None:
            params = [p for p in inspect.signature(attr).parameters if p not in SDK_OPTIONS]
            extra = list(getattr(attr, "__flexen_extra__", ()))
            entry = out.setdefault(op, {})
            if flavour in entry:
                raise SystemExit(f"operation {op} is bound twice in {flavour}: {entry[flavour]['method']} and {prefix}.{name}")
            entry[flavour] = {"method": f"{prefix}.{name}", "params": params, "extra": extra}
        elif type(attr).__module__.startswith("flexenai._client"):
            walk(attr, f"{prefix}.{name}", seen, out, flavour)


surface: dict[str, dict[str, object]] = {}
walk(flexenai.Flexen("flx_test_surface"), "Flexen", set(), surface, "sync")
walk(flexenai.AsyncFlexen("flx_test_surface"), "AsyncFlexen", set(), surface, "async")
print(json.dumps({"operations": surface, "errorCodes": sorted(ERROR_CLASS_BY_CODE), "sdkOptions": list(SDK_OPTIONS)}))
