#!/usr/bin/env python
"""Generate a MapKit JS JWT token from an Apple .p8 private key.

Usage:
    venv/bin/python scripts/generate_mapkit_token.py --team-id YOUR_TEAM_ID

The token is printed to stdout so it can be captured:
    export MAPKIT_TOKEN=$(venv/bin/python scripts/generate_mapkit_token.py --team-id YOUR_TEAM_ID)
"""

import argparse
import glob
import sys
import time

import jwt


def main():
    parser = argparse.ArgumentParser(description="Generate a MapKit JS token")
    parser.add_argument("--team-id", required=True, help="Apple Developer Team ID")
    parser.add_argument("--key-file", help="Path to .p8 private key (default: auto-detect from config/)")
    parser.add_argument("--key-id", help="Key ID (default: extracted from .p8 filename)")
    parser.add_argument("--ttl", type=int, default=15778800, help="Token TTL in seconds (default: ~6 months)")
    args = parser.parse_args()

    # Auto-detect key file
    key_file = args.key_file
    if not key_file:
        matches = glob.glob("config/AuthKey_*.p8")
        if not matches:
            print("Error: no config/AuthKey_*.p8 found. Use --key-file.", file=sys.stderr)
            sys.exit(1)
        key_file = matches[0]

    # Extract key ID from filename
    key_id = args.key_id
    if not key_id:
        # AuthKey_XXXXXXXXXX.p8 -> XXXXXXXXXX
        basename = key_file.rsplit("/", 1)[-1]
        key_id = basename.replace("AuthKey_", "").replace(".p8", "")

    with open(key_file) as f:
        private_key = f.read()

    now = int(time.time())
    token = jwt.encode(
        {"iss": args.team_id, "iat": now, "exp": now + args.ttl},
        private_key,
        algorithm="ES256",
        headers={"kid": key_id, "typ": "JWT", "alg": "ES256"},
    )

    print(token)


if __name__ == "__main__":
    main()
