"""Generate a reproducible synthetic input pack and separate evaluation labels."""
import argparse
import json

from hrtrustgraph.deterministic.synthetic import DEFAULT_AS_OF, generate_pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Pack directory; creates input/ and evaluator-only truth/ beneath it")
    parser.add_argument("--n", type=int, default=5000, help="Underlying people, before optional employment history")
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--as-of", default=DEFAULT_AS_OF)
    parser.add_argument("--profile", choices=("development", "validation", "final"), default="development")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly regenerate an existing pack, replacing its source files and labels")
    args = parser.parse_args()
    try:
        manifest = generate_pack(args.output, n=args.n, seed=args.seed, as_of=args.as_of, profile=args.profile, overwrite=args.overwrite)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Generation error: {exc}\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
