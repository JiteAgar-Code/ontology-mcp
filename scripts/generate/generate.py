"""
generate.py — Master artifact generation pipeline.

Usage:
    python scripts/generate.py --schema login --version 1.0.0
    python scripts/generate.py --schema login --version 1.0.0 --only owl shacl
    python scripts/generate.py --list

What it does:
    Reads schemas/{schema}/v{version}/{schema}.yaml and runs all
    generator scripts in order, writing output to:
        artifacts/{schema}/v{version}/owl/
        artifacts/{schema}/v{version}/shacl/
        artifacts/{schema}/v{version}/skos/
        artifacts/{schema}/v{version}/descriptors/
        artifacts/{schema}/v{version}/rules/
        artifacts/{schema}/v{version}/jsonld/

    Each generator is a standalone Python module (gen_*.py) that can
    also be run individually for debugging.

Pipeline order matters:
    owl → shacl → skos → descriptors → rules → jsonld
    (later stages may reference artifacts from earlier ones)

Flags:
    --schema   : schema name from registry (e.g. login)
    --version  : semver string (e.g. 1.0.0)
    --only     : space-separated list of stages to run (skip others)
    --list     : print all registered schemas and exit
"""

import sys
import time
import argparse
from pathlib import Path

# Add scripts/ to path so generators can import _yaml_loader
sys.path.insert(0, str(Path(__file__).parent))

from _yaml_loader import load_registry


# ── Stage registry ────────────────────────────────────────────
# Each entry: (stage_name, module_name, function_name)
STAGES = [
    ("owl",         "gen_owl",         "generate_owl"),
    ("shacl",       "gen_shacl",       "generate_shacl"),
    ("skos",        "gen_skos",        "generate_skos"),
    ("descriptors", "gen_descriptors", "generate_descriptors"),
    ("rules",       "gen_rules",       "generate_rules"),
    ("jsonld",      "gen_jsonld",      "generate_jsonld"),
]


def _import_generator(module_name: str, func_name: str):
    """Dynamically import a generator function from scripts/."""
    import importlib
    mod  = importlib.import_module(module_name)
    func = getattr(mod, func_name)
    return func


def list_schemas() -> None:
    registry = load_registry()
    print("\nRegistered schemas:")
    print(f"  {'NAME':<20} {'CURRENT VERSION':<16} STATUS")
    print(f"  {'-'*20} {'-'*16} ------")
    for s in registry.get("schemas", []):
        print(f"  {s['name']:<20} {s['current_version']:<16} {s.get('status','')}")
    print()


def run_pipeline(schema: str, version: str, only: list[str] | None = None) -> bool:
    stages_to_run = [s for s in STAGES if (only is None or s[0] in only)]

    print(f"\n{'═'*60}")
    print(f"  Artifact Generation Pipeline")
    print(f"  Schema  : {schema}")
    print(f"  Version : {version}")
    print(f"  Stages  : {', '.join(s[0] for s in stages_to_run)}")
    print(f"{'═'*60}")

    results = {}
    overall_start = time.time()

    for stage_name, module_name, func_name in stages_to_run:
        print(f"\n▶ [{stage_name.upper()}]")
        start = time.time()
        try:
            fn = _import_generator(module_name, func_name)
            fn(schema, version)
            elapsed = time.time() - start
            results[stage_name] = ("✅ OK", elapsed)
            print(f"  └─ done in {elapsed:.2f}s")
        except Exception as exc:
            elapsed = time.time() - start
            results[stage_name] = (f"❌ FAILED: {exc}", elapsed)
            print(f"  └─ FAILED in {elapsed:.2f}s: {exc}")

    # ── Summary ───────────────────────────────────────────
    total = time.time() - overall_start
    print(f"\n{'─'*60}")
    print(f"  Pipeline Summary  ({total:.2f}s total)")
    print(f"{'─'*60}")
    all_ok = True
    for stage, (status, elapsed) in results.items():
        print(f"  {stage:<14} {status}  ({elapsed:.2f}s)")
        if status.startswith("❌"):
            all_ok = False
    print(f"{'─'*60}")

    if all_ok:
        print(f"\n  All artifacts written to: artifacts/{schema}/v{version}/\n")
    else:
        print(f"\n  Some stages failed. Fix errors and re-run.\n")

    return all_ok


def main():
    parser = argparse.ArgumentParser(
        description="Generate ontology artifacts from a LinkML YAML schema"
    )
    parser.add_argument("--schema",  help="Schema name (e.g. login)")
    parser.add_argument("--version", help="Schema version (e.g. 1.0.0)")
    parser.add_argument(
        "--only", nargs="+",
        choices=[s[0] for s in STAGES],
        help="Run only these stages"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all registered schemas and exit"
    )
    args = parser.parse_args()

    if args.list:
        list_schemas()
        return

    if not args.schema or not args.version:
        parser.error("--schema and --version are required (unless using --list)")

    success = run_pipeline(args.schema, args.version, args.only)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
