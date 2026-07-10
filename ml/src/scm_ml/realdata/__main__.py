from __future__ import annotations

import argparse
from pathlib import Path

from .online_retail import build_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the real weekly demand dataset.")
    parser.add_argument("--raw", type=Path, default=Path("data/raw/online_retail_ii"))
    parser.add_argument("--out", type=Path, default=Path("data/real_demand"))
    args = parser.parse_args(argv)

    manifest = build_dataset(args.raw, args.out)
    print(f"Wrote {manifest['dataset_id']} to {args.out}")
    print(f"  weeks {manifest['first_week']} .. {manifest['last_week']}")
    for name, info in manifest["files"].items():
        print(f"  {name}: {info['rows']} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
