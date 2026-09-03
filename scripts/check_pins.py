#!/usr/bin/env python3
"""Check both host catalogs against the repositories they reference.

This is the half the offline tests cannot do, because it needs the network.

The failure it exists to catch: a plugin repo ships version 1.4.0, nobody updates
its entries here, and one host keeps installing 1.3.0 while the other quietly moves.
Neither repository can notice that alone, because the pieces live apart.

Usage:
    python3 scripts/check_pins.py          # check every entry
    python3 scripts/check_pins.py showme   # check one
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
CODEX_MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
SHA = re.compile(r"^[0-9a-f]{40}$")
GIT_TIMEOUT_SECONDS = 60


class GitTimeoutError(RuntimeError):
    """Raised when a bounded Git operation does not finish."""


def run(args, **kwargs):
    environment = os.environ.copy()
    environment.update(kwargs.pop("env", {}))
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=environment,
            **kwargs,
        )
    except subprocess.TimeoutExpired as error:
        raise GitTimeoutError(
            f"git operation timed out after {GIT_TIMEOUT_SECONDS} seconds"
        ) from error


def load_plugins(path):
    return json.loads(path.read_text(encoding="utf8"))["plugins"]


def source_problem(name, host, source):
    """Return why a catalog source is unsafe or malformed, if anything."""
    if not isinstance(source, dict):
        return f"{name}: {host} source must be an object"
    if source.get("source") != "url":
        return f"{name}: {host} source type must be url"

    url = source.get("url")
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
        port = parsed.port if parsed else None
    except ValueError:
        parsed = None
        port = None
    path_parts = parsed.path.split("/") if parsed else []
    url_is_trusted = (
        parsed is not None
        and not any(character.isspace() or ord(character) < 32 for character in url)
        and parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.username is None
        and parsed.password is None
        and port is None
        and not parsed.query
        and not parsed.fragment
        and len(path_parts) == 3
        and all(path_parts[1:])
        and path_parts[-1].endswith(".git")
        and "\\" not in parsed.path
    )
    if not url_is_trusted:
        return (
            f"{name}: {host} source URL must be a credential-free "
            "https://github.com/OWNER/REPO.git URL"
        )

    sha = source.get("sha")
    if not isinstance(sha, str) or SHA.fullmatch(sha) is None:
        return f"{name}: {host} source must pin a full lowercase 40-character sha"
    return None


def catalog_alignment_problems(claude_plugins, codex_plugins):
    """Return source drift that would make the two hosts install different code."""
    problems = []
    claude_names = [plugin["name"] for plugin in claude_plugins]
    codex_names = [plugin["name"] for plugin in codex_plugins]
    if claude_names != codex_names:
        problems.append(
            "catalog plugin names/order differ: "
            f"Claude Code has {claude_names}; Codex has {codex_names}"
        )

    claude_by_name = {plugin["name"]: plugin for plugin in claude_plugins}
    codex_by_name = {plugin["name"]: plugin for plugin in codex_plugins}
    for name in sorted(set(claude_by_name) & set(codex_by_name)):
        raw_claude_source = claude_by_name[name].get("source", {})
        raw_codex_source = codex_by_name[name].get("source", {})
        claude_source = raw_claude_source if isinstance(raw_claude_source, dict) else {}
        codex_source = raw_codex_source if isinstance(raw_codex_source, dict) else {}
        if codex_source.get("source") != claude_source.get("source"):
            problems.append(f"{name}: Claude Code and Codex source types differ")
        if codex_source.get("url") != claude_source.get("url"):
            problems.append(f"{name}: Claude Code and Codex repository URLs differ")
        codex_sha = codex_source.get("sha")
        if codex_sha != claude_source.get("sha"):
            problems.append(f"{name}: Claude Code and Codex pinned SHAs differ")
    return problems


def read_manifest(work, ref, manifest_path, name):
    show = run(["git", "-C", work, "show", f"{ref}:{manifest_path}"])
    if show.returncode != 0:
        return None, f"{name}: no {manifest_path} at {ref[:12]}"
    try:
        manifest = json.loads(show.stdout)
    except json.JSONDecodeError as error:
        return None, f"{name}: {manifest_path} at {ref[:12]} is not valid JSON: {error}"
    if not isinstance(manifest, dict):
        return None, f"{name}: {manifest_path} at {ref[:12]} is not a JSON object"
    return manifest, None


def check(claude_plugin, codex_plugin):
    name = claude_plugin["name"]
    claude_source = claude_plugin["source"]
    codex_source = codex_plugin["source"]

    for host, source in (
        ("Claude Code", claude_source),
        ("Codex", codex_source),
    ):
        problem = source_problem(name, host, source)
        if problem:
            return problem

    url, sha = claude_source["url"], claude_source["sha"]
    listed = claude_plugin["version"]

    work = tempfile.mkdtemp(prefix=f"pin-{name}-")
    try:
        # blob:none keeps this cheap: metadata now, file contents only when asked for.
        clone = run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", url, work])
        if clone.returncode != 0:
            return f"{name}: cannot clone {url}\n{clone.stderr.strip()}"

        if run(["git", "-C", work, "cat-file", "-e", f"{sha}^{{commit}}"]).returncode != 0:
            return f"{name}: pinned commit {sha} does not exist in {url}"

        claude_manifest, error = read_manifest(work, sha, ".claude-plugin/plugin.json", name)
        if error:
            return error
        if claude_manifest.get("name") != name:
            return f"{name}: Claude manifest at {sha[:12]} declares {claude_manifest.get('name')}"
        if claude_manifest.get("version") != listed:
            return (
                f"{name}: this catalog says {listed}, but the pinned commit {sha[:12]} "
                f"declares {claude_manifest.get('version')}. Update this entry's version and sha, or re-pin it."
            )

        codex_sha = codex_source["sha"]
        codex_manifest, error = read_manifest(work, codex_sha, ".codex-plugin/plugin.json", name)
        if error:
            return error
        if codex_manifest.get("name") != name:
            return f"{name}: Codex manifest at {codex_sha[:12]} declares {codex_manifest.get('name')}"
        if codex_manifest.get("version") != listed:
            return (
                f"{name}: Claude catalog says {listed}, but the Codex manifest at "
                f"{codex_sha[:12]} declares {codex_manifest.get('version')}"
            )

        print(f"  {name}: Claude Code and Codex {listed} match {sha[:12]}")
        return None
    except GitTimeoutError as error:
        return f"{name}: {error}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    claude_plugins = load_plugins(CLAUDE_MARKETPLACE)
    codex_plugins = load_plugins(CODEX_MARKETPLACE)
    wanted = sys.argv[1:]
    if wanted:
        known = {plugin["name"] for plugin in claude_plugins}
        missing = set(wanted) - known
        if missing:
            print(f"no such plugin in the catalog: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

        wanted_names = set(wanted)
        claude_plugins = [plugin for plugin in claude_plugins if plugin["name"] in wanted_names]
        codex_plugins = [plugin for plugin in codex_plugins if plugin["name"] in wanted_names]

    alignment_problems = catalog_alignment_problems(claude_plugins, codex_plugins)
    for message in alignment_problems:
        print(f"::error::{message}", file=sys.stderr)
    if alignment_problems:
        return 1

    codex_by_name = {plugin["name"]: plugin for plugin in codex_plugins}
    plugins = claude_plugins

    problems = [
        message
        for message in (check(plugin, codex_by_name[plugin["name"]]) for plugin in plugins)
        if message
    ]
    for message in problems:
        print(f"::error::{message}", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} of {len(plugins)} entries are out of step.", file=sys.stderr)
        return 1

    print(f"\nAll {len(plugins)} plugin sources passed their active host-catalog checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
