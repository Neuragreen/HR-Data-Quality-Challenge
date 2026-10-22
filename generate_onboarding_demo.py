"""Prepare the optional five-source synthetic example for browser upload."""
import argparse
import json

from hrtrustgraph.deterministic.onboarding import generate_onboarding_pack

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='datasets/onboarding')
    args = parser.parse_args()
    try:
        print(json.dumps(generate_onboarding_pack(args.output), indent=2))
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + '\n')
