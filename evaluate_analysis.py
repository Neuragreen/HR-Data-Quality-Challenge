"""Evaluate a deterministic analysis using separately held synthetic labels."""
import argparse
import json

from hrtrustgraph.deterministic.evaluation import evaluate_analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", "--predictions", dest="output", required=True, help="Analysis directory containing issues.csv and employees.csv")
    parser.add_argument("--truth", required=True, help="Evaluator-only truth directory, never the detector input directory")
    parser.add_argument("--report", required=True, help="Destination evaluation JSON")
    args = parser.parse_args()
    result = evaluate_analysis(args.output, args.truth, args.report)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
