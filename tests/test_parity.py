"""CLI and Hermes adapter must be the same implementation."""

import json

from sfx_forge import cli
from sfx_forge.tools import handle_generate, handle_verify


def test_cli_and_tool_produce_identical_bytes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SFX_FORGE_ROOT", str(tmp_path / "tools"))
    tool_reply = json.loads(handle_generate({"presets": ["hit", "coin"], "seed": 4, "folder": "p"}))

    rc = cli.main(["generate", "--preset", "hit", "--preset", "coin", "--seed", "4",
                   "--folder", "p", "--root", str(tmp_path / "cli"), "--json"])
    cli_reply = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert [c["sha256"] for c in tool_reply["cues"]] == [c["sha256"] for c in cli_reply["cues"]]
    assert [c["sample_count"] for c in tool_reply["cues"]] == [c["sample_count"] for c in cli_reply["cues"]]


def test_tool_and_cli_verify_agree(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SFX_FORGE_ROOT", str(tmp_path / "tools"))
    handle_generate({"presets": ["hit"], "seed": 0, "folder": "p"})
    tool_reply = json.loads(handle_verify({"folder": "p", "presets": ["hit"]}))

    rc = cli.main(["verify", "--folder", "p", "--preset", "hit",
                   "--root", str(tmp_path / "tools"), "--json"])
    cli_reply = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert tool_reply["passed"] == cli_reply["passed"] is True
    assert tool_reply["results"][0]["sha256"] == cli_reply["results"][0]["sha256"]


def test_tool_rejects_bad_folder_as_json(tmp_path, monkeypatch):
    monkeypatch.setenv("SFX_FORGE_ROOT", str(tmp_path))
    reply = json.loads(handle_verify({"folder": "../etc"}))
    assert reply["kind"] == "rejected"
