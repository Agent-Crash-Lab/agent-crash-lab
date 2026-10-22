"""Create a QA plan from a target descriptor and sample data; never runs an Agent."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness/src"))
from harness.planning import QaPlanner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--sample-data", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.target) != bool(args.sample_data):
        parser.error("--target and --sample-data must be supplied together")
    try:
        target = json.loads(args.target.read_text()) if args.target else None
        sample = json.loads(args.sample_data.read_text()) if args.sample_data else None
        plan = QaPlanner(ROOT).build(target, sample)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError:
        parser.exit(2, "Output already exists; choose a new plan file.\n")
    print(f"Prepared {args.output}; READY means executable, not PASS. No simulation was run.")


if __name__ == "__main__":
    main()
