"""Offline checks on the Claude Code and Codex catalogs.

These run without network access, so they only cover what the files themselves can be
wrong about. The live check - does the pinned commit exist, and does the plugin it
points at really advertise the version listed here for both hosts - lives in CI,
because it needs to fetch each repository.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
CODEX_MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CHECKOUT_V6_SHA = "d23441a48e516b6c34aea4fa41551a30e30af803"
MARKETPLACES = {
    "Claude Code": CLAUDE_MARKETPLACE,
    "Codex": CODEX_MARKETPLACE,
}

SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def load(path):
    return json.loads(path.read_text(encoding="utf8"))


def load_all():
    return {host: load(path) for host, path in MARKETPLACES.items()}


class MarketplaceTest(unittest.TestCase):
    def test_ci_pins_checkout_without_credentials_and_gates_the_live_job(self):
        workflow = CI_WORKFLOW.read_text(encoding="utf8")
        checkout = f"uses: actions/checkout@{CHECKOUT_V6_SHA} # v6"

        self.assertEqual(workflow.count(checkout), 2)
        self.assertEqual(workflow.count("persist-credentials: false"), 2)
        live_job = workflow.split("\n  live:\n", maxsplit=1)[1]
        self.assertIn("needs: offline", live_job)
        self.assertIn("timeout-minutes: 10", live_job)

    def test_files_are_valid_json_with_the_expected_name(self):
        # The marketplace name is what appears after the @ in each host's install
        # command. It is published in both plugins' READMEs, so renaming it breaks
        # their docs and every existing install.
        for host, data in load_all().items():
            with self.subTest(host=host):
                self.assertEqual(data["name"], "jmarlique-tools")
                self.assertIn("plugins", data)
                self.assertTrue(data["plugins"], f"the {host} catalog lists no plugins")

    def test_plugin_names_are_unique(self):
        for host, data in load_all().items():
            names = [p["name"] for p in data["plugins"]]
            with self.subTest(host=host):
                self.assertEqual(len(names), len(set(names)), f"duplicate plugin names in {host}: {names}")

    def test_catalogs_list_the_same_plugins_in_the_same_order(self):
        catalogs = load_all()
        claude_names = [plugin["name"] for plugin in catalogs["Claude Code"]["plugins"]]
        codex_names = [plugin["name"] for plugin in catalogs["Codex"]["plugins"]]
        self.assertEqual(codex_names, claude_names)

    def test_catalog_sources_share_urls_and_matching_pins(self):
        catalogs = load_all()
        claude = {plugin["name"]: plugin for plugin in catalogs["Claude Code"]["plugins"]}
        codex = {plugin["name"]: plugin for plugin in catalogs["Codex"]["plugins"]}

        for name, claude_plugin in claude.items():
            with self.subTest(plugin=name):
                claude_source = claude_plugin["source"]
                codex_source = codex[name]["source"]
                self.assertEqual(codex_source.get("source"), claude_source.get("source"))
                self.assertEqual(codex_source.get("url"), claude_source.get("url"))
                self.assertEqual(codex_source.get("sha"), claude_source.get("sha"))

    def test_every_entry_is_remote_and_pinned(self):
        """This repository is a catalog and ships no plugin code of its own, so every
        entry has to point at another repository and name an exact commit. Exact pins
        keep installs stable when an upstream repository moves."""
        for host, data in load_all().items():
            for plugin in data["plugins"]:
                with self.subTest(host=host, plugin=plugin["name"]):
                    source = plugin["source"]
                    self.assertIsInstance(
                        source,
                        dict,
                        f"{plugin['name']}: this repo holds no plugin code, so a relative source cannot work",
                    )
                    self.assertEqual(source.get("source"), "url", f"{plugin['name']}: expected a url source")
                    self.assertTrue(
                        source.get("url", "").startswith("https://github.com/"),
                        f"{plugin['name']}: url must be a https github url",
                    )
                    self.assertTrue(
                        source.get("url", "").endswith(".git"),
                        f"{plugin['name']}: url must end in .git",
                    )
                    self.assertRegex(
                        source.get("sha", ""),
                        SHA,
                        f"{plugin['name']}: must pin a full 40-character commit sha",
                    )

    def test_every_claude_entry_carries_what_the_plugin_browser_shows(self):
        for plugin in load(CLAUDE_MARKETPLACE)["plugins"]:
            for field in ("name", "description", "version"):
                self.assertTrue(plugin.get(field), f"{plugin['name']}: missing {field}")
            self.assertRegex(plugin["version"], SEMVER, f"{plugin['name']}: version is not X.Y.Z")

    def test_codex_catalog_has_native_interface_and_policy_metadata(self):
        data = load(CODEX_MARKETPLACE)
        self.assertEqual(data["interface"]["displayName"], "Jmarlique Tools")

        for plugin in data["plugins"]:
            with self.subTest(plugin=plugin["name"]):
                self.assertEqual(
                    plugin["policy"],
                    {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                )
                self.assertEqual(plugin["category"], "Productivity")


if __name__ == "__main__":
    unittest.main()
