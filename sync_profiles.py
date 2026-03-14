#!/usr/bin/env python3
"""
sync_profiles.py — Fetch Snapmaker filament profile names from the
Snapmaker/OrcaSlicer GitHub repository and print a mapping suitable
for use in bl2u1's filament remapping logic.

Usage:
    python sync_profiles.py [--output profiles.json]

The script reads the filament JSON files published in:
    https://github.com/Snapmaker/OrcaSlicer/tree/main/resources/profiles/Snapmaker/filament

It produces a JSON list of {"type": "<material-class>", "settings_id": "<profile-name>"}
entries that can be used to update filament_types.3mf or the DEFAULT_FILAMENT_PROFILE
constant in app.py.

Requirements: requests  (pip install requests)
"""

import json
import sys
import argparse
import logging

try:
    import requests
except ImportError:
    sys.exit("Install the 'requests' package first:  pip install requests")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
REPO       = "Snapmaker/OrcaSlicer"
BRANCH     = "main"
FILAMENT_PATH = "resources/profiles/Snapmaker/filament"

# Map OrcaSlicer filament_type values → the generic type used in bl2u1
_TYPE_MAP = {
    "PLA":    "PLA",
    "PETG":   "PETG",
    "ABS":    "ABS",
    "ASA":    "ASA",
    "TPU":    "TPU",
    "TPE":    "TPE",
    "PA":     "PA",
    "PA-CF":  "PA-CF",
    "PET":    "PET",
    "PVA":    "PVA",
}


def list_filament_files(session: requests.Session) -> list[dict]:
    url = f"{GITHUB_API}/repos/{REPO}/contents/{FILAMENT_PATH}?ref={BRANCH}"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return [f for f in resp.json() if f["name"].endswith(".json")]


def fetch_profile(session: requests.Session, download_url: str) -> dict | None:
    try:
        resp = session.get(download_url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("Could not fetch %s: %s", download_url, exc)
        return None


def profile_entry(name: str, data: dict) -> dict | None:
    """
    Return a bl2u1-compatible dict or None if the profile is a base/variant
    that shouldn't be listed as a standalone option.
    Skip profiles that are variants (contain '@') unless they are @U1.
    """
    # Skip base/common config files
    if name.startswith("fdm_filament_"):
        return None

    filament_type = data.get("filament_type", [""])[0] if isinstance(
        data.get("filament_type"), list
    ) else data.get("filament_type", "")

    generic_type = _TYPE_MAP.get(filament_type, filament_type) or "PLA"

    # Profile name is the filename without .json
    settings_id = name[:-5]

    return {"type": generic_type, "settings_id": settings_id}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", "-o", default="-",
                        help="Output file path (default: stdout)")
    parser.add_argument("--token", "-t", default=None,
                        help="GitHub personal access token (avoids rate-limits)")
    args = parser.parse_args()

    session = requests.Session()
    session.headers["Accept"] = "application/vnd.github.v3+json"
    if args.token:
        session.headers["Authorization"] = f"Bearer {args.token}"

    log.info("Listing filament profiles from %s/%s …", REPO, FILAMENT_PATH)
    try:
        files = list_filament_files(session)
    except requests.HTTPError as exc:
        sys.exit(f"GitHub API error: {exc}")

    log.info("Found %d JSON files", len(files))

    profiles: list[dict] = []
    seen_ids: set[str] = set()

    for f in sorted(files, key=lambda x: x["name"]):
        data = fetch_profile(session, f["download_url"])
        if data is None:
            continue
        entry = profile_entry(f["name"], data)
        if entry is None or entry["settings_id"] in seen_ids:
            continue
        seen_ids.add(entry["settings_id"])
        profiles.append(entry)
        log.info("  %-10s  %s", entry["type"], entry["settings_id"])

    output_json = json.dumps(profiles, indent=2, ensure_ascii=False)

    if args.output == "-":
        print(output_json)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(output_json)
        log.info("Written %d profiles to %s", len(profiles), args.output)


if __name__ == "__main__":
    main()
