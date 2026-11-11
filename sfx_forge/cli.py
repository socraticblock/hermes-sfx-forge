"""Command-line interface: generate and verify, with a JSON mode."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import RequestRejected, generate_pack, verify_file, verify_pack
from .paths import PathRejected, workspace_root
from .presets import preset_names


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sfx-forge", description="Deterministic game SFX synthesis and delivery gate.")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="render presets into a pack folder")
    g.add_argument("--preset", action="append", choices=preset_names(), help="repeatable; default: all")
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--folder", default="pack")
    g.add_argument("--root", default=None)
    g.add_argument("--overwrite", action="store_true")
    g.add_argument("--json", action="store_true")

    v = sub.add_parser("verify", help="verify a file or a pack folder")
    v.add_argument("path", nargs="?", default=None)
    v.add_argument("--folder", default=None)
    v.add_argument("--preset", action="append", choices=preset_names())
    v.add_argument("--root", default=None)
    v.add_argument("--json", action="store_true")

    sub.add_parser("presets", help="list preset names")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "presets":
            print("\n".join(preset_names()))
            return 0
        if args.command == "generate":
            manifest = generate_pack(presets=args.preset, seed=args.seed, folder=args.folder,
                                     root=args.root, overwrite=args.overwrite)
            if args.json:
                print(json.dumps(manifest, indent=2, sort_keys=True))
            else:
                for cue in manifest["cues"]:
                    print(f"{cue['preset']:8} {cue['duration_ms']:4} ms  "
                          f"{cue['sample_count']:6} samples  {cue['sha256'][:12]}  "
                          f"{'pass' if cue['passed'] else 'FAIL'}")
            return 0 if manifest["passed"] else 1
        if args.command == "verify":
            if args.folder:
                result = verify_pack(args.folder, root=args.root, presets=args.preset)
            elif args.path:
                result = verify_file(Path(args.path))
            else:
                raise RequestRejected("verify needs a path or --folder")
            print(json.dumps(result, indent=2, sort_keys=True) if args.json
                  else f"{'pass' if result.get('passed') else 'FAIL'}  {result}")
            return 0 if result.get("passed") else 1
    except (RequestRejected, PathRejected) as exc:
        print(json.dumps({"error": str(exc)}) if getattr(args, "json", False) else f"error: {exc}",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
