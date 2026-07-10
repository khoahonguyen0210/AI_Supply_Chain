from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import SyntheticConfig
from .generator import generate_world
from .io import write_world
from .validation import validate_world


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the synthetic SCM world.")
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--seed", type=int, default=SyntheticConfig().seed)
    args = parser.parse_args(argv)

    world = generate_world(SyntheticConfig(seed=args.seed))
    issues = validate_world(world)
    if issues:
        print("Validation failed:", *issues[:20], sep="\n  ", file=sys.stderr)
        return 1
    manifest = write_world(world, args.out)
    print(f"Wrote {manifest['dataset_id']} to {args.out}")
    for name, info in manifest["files"].items():
        print(f"  {name}: {info['rows']} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
