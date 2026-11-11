"""The plugin entry point must register both tools with valid schemas."""

import importlib.util

from sfx_forge import tools


class FakeCtx:
    def __init__(self):
        self.calls = []

    def register_tool(self, name=None, toolset=None, schema=None, handler=None):
        self.calls.append({"name": name, "toolset": toolset, "schema": schema, "handler": handler})


def test_register_wires_both_tools():
    ctx = FakeCtx()
    tools.register_tools(ctx)
    assert [c["name"] for c in ctx.calls] == ["sfx_generate", "sfx_verify"]
    for call in ctx.calls:
        assert call["toolset"] == "sfx_forge"
        assert call["schema"]["name"] == call["name"]
        assert call["schema"]["parameters"]["type"] == "object"
        assert callable(call["handler"])


def test_root_entry_point_registers(monkeypatch):
    spec = importlib.util.spec_from_file_location("plugin_entry", _root_init())
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ctx = FakeCtx()
    mod.register(ctx)
    assert len(ctx.calls) == 2


def _root_init():
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "__init__.py"
