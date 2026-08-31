"""Offline checks on the catalog.

These run without network access, so they only cover what the file itself can be
wrong about. The live check - does the pinned commit exist, and does the plugin it
points at really advertise the version listed here - lives in CI, because it needs
to fetch each repository.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"

SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def load():
    return json.loads(MARKETPLACE.read_text(encoding="utf8"))


class MarketplaceTest(unittest.TestCase):
    def test_file_is_valid_json_with_the_expected_name(self):
        data = load()
        # The marketplace name is what appears after the @ in `/plugin install x@name`.
        # It is published in both plugins' READMEs, so renaming it breaks their docs
        # and every existing install.
        self.assertEqual(data["name"], "jmarlique-tools")
        self.assertIn("plugins", data)
        self.assertTrue(data["plugins"], "the catalog lists no plugins")

    def test_plugin_names_are_unique(self):
        names = [p["name"] for p in load()["plugins"]]
        self.assertEqual(len(names), len(set(names)), f"duplicate plugin names: {names}")

    def test_every_entry_is_remote_and_pinned(self):
        """This repository is a catalog and ships no plugin code of its own, so every
        entry has to point at another repository and name an exact commit. An unpinned
        entry silently changes what installs whenever that repository moves."""
        for plugin in load()["plugins"]:
            source = plugin["source"]
            self.assertIsInstance(
                source, dict, f"{plugin['name']}: this repo holds no plugin code, so a relative source cannot work"
            )
            self.assertEqual(source.get("source"), "url", f"{plugin['name']}: expected a url source")
            self.assertTrue(
                source.get("url", "").startswith("https://github.com/"),
                f"{plugin['name']}: url must be a https github url",
            )
            self.assertTrue(source.get("url", "").endswith(".git"), f"{plugin['name']}: url must end in .git")
            self.assertRegex(
                source.get("sha", ""),
                SHA,
                f"{plugin['name']}: must pin a full 40-character commit sha",
            )

    def test_every_entry_carries_what_the_plugin_browser_shows(self):
        for plugin in load()["plugins"]:
            for field in ("name", "description", "version"):
                self.assertTrue(plugin.get(field), f"{plugin['name']}: missing {field}")
            self.assertRegex(plugin["version"], SEMVER, f"{plugin['name']}: version is not X.Y.Z")


if __name__ == "__main__":
    unittest.main()
