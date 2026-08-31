#!/usr/bin/env python3
"""Check every catalog entry against the repository it pins.

This is the half the offline tests cannot do, because it needs the network.

The failure it exists to catch: a plugin repo ships version 1.4.0, nobody updates
its entry here, and every install keeps advertising 1.3.0 while quietly delivering
whatever the pinned commit holds. Neither repository can notice that alone, because
the two halves live apart.

Usage:
    python3 scripts/check_pins.py          # check every entry
    python3 scripts/check_pins.py showme   # check one
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def check(plugin):
    name = plugin["name"]
    source = plugin["source"]
    url, sha = source["url"], source["sha"]
    listed = plugin["version"]

    work = tempfile.mkdtemp(prefix=f"pin-{name}-")
    try:
        # blob:none keeps this cheap: metadata now, file contents only when asked for.
        clone = run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", url, work])
        if clone.returncode != 0:
            return f"{name}: cannot clone {url}\n{clone.stderr.strip()}"

        if run(["git", "-C", work, "cat-file", "-e", f"{sha}^{{commit}}"]).returncode != 0:
            return f"{name}: pinned commit {sha} does not exist in {url}"

        show = run(["git", "-C", work, "show", f"{sha}:.claude-plugin/plugin.json"])
        if show.returncode != 0:
            return f"{name}: no .claude-plugin/plugin.json at {sha[:12]}"

        try:
            actual = json.loads(show.stdout).get("version")
        except json.JSONDecodeError as error:
            return f"{name}: plugin.json at {sha[:12]} is not valid JSON: {error}"

        if actual != listed:
            return (
                f"{name}: this catalog says {listed}, but the pinned commit {sha[:12]} "
                f"declares {actual}. Update this entry's version and sha, or re-pin it."
            )

        print(f"  {name}: {listed} matches {sha[:12]}")
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    plugins = json.loads(MARKETPLACE.read_text(encoding="utf8"))["plugins"]
    wanted = sys.argv[1:]
    if wanted:
        plugins = [p for p in plugins if p["name"] in wanted]
        missing = set(wanted) - {p["name"] for p in plugins}
        if missing:
            print(f"no such plugin in the catalog: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    problems = [message for message in (check(p) for p in plugins) if message]
    for message in problems:
        print(f"::error::{message}", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} of {len(plugins)} entries are out of step.", file=sys.stderr)
        return 1

    print(f"\nAll {len(plugins)} entries match the commits they pin.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
