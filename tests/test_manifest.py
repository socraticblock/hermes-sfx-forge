"""Manifest-to-code contract, checked without a YAML dependency.

Hermes' real plugin loader requires ``capabilities`` to be a *list* of capability
ids. A mapping is accepted by ``hermes plugins validate`` but produces a load-time
warning in the host, which is how this defect survived the first round of tests.
"""

import re
from pathlib import Path

from sfx_forge.tools import TOOLS

MANIFEST = (Path(__file__).resolve().parents[1] / "plugin.yaml").read_text(encoding="utf-8")


def test_capabilities_is_a_list():
    match = re.search(r"^capabilities:\s*(.*)$", MANIFEST, re.MULTILINE)
    assert match, "plugin.yaml must declare capabilities"
    assert match.group(1).strip() == "[]", (
        "Hermes requires capabilities to be a YAML list of capability ids; "
        "a mapping logs 'must be a list' and is ignored at load time"
    )


def test_declared_tools_match_registrations():
    block = re.search(r"^provides_tools:\s*$\n((?:\s+-\s+\S+\n)+)", MANIFEST, re.MULTILINE)
    assert block, "plugin.yaml must declare provides_tools as a list"
    declared = [line.strip()[2:].strip() for line in block.group(1).strip().splitlines()]
    registered = [schema["name"] for schema, _handler in TOOLS]
    assert declared == registered


def test_requires_hermes_floor_is_a_strict_version():
    match = re.search(r'^requires_hermes:\s*"([^"]+)"$', MANIFEST, re.MULTILINE)
    assert match, "requires_hermes must be quoted"
    spec = match.group(1)
    assert re.fullmatch(r">=\d+\.\d+\.\d+", spec), f"expected >=X.Y.Z, got {spec}"
