"""Focused tests for the network-backed dual-host pin checker."""

from contextlib import redirect_stdout
from contextlib import redirect_stderr
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_pins", ROOT / "scripts" / "check_pins.py")
CHECK_PINS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK_PINS)


def run_git(repo, *args):
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return subprocess.run(
        ["git", "-c", "commit.gpgSign=false", "-c", f"core.hooksPath={os.devnull}", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout.strip()


class PluginRepository:
    def __init__(self, test_case):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "plugin"
        self.path.mkdir()
        run_git(self.path, "init", "--quiet", "--initial-branch=main")
        run_git(self.path, "config", "user.email", "tests@example.invalid")
        run_git(self.path, "config", "user.name", "Catalog Tests")
        test_case.addCleanup(self.tempdir.cleanup)

    def write_manifest(self, host, value):
        path = self.path / f".{host}-plugin" / "plugin.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            path.write_text(value, encoding="utf8")
        else:
            path.write_text(json.dumps(value), encoding="utf8")

    def remove_manifest(self, host):
        path = self.path / f".{host}-plugin" / "plugin.json"
        path.unlink()

    def commit(self, message="fixture"):
        run_git(self.path, "add", "--all")
        run_git(self.path, "commit", "--quiet", "--message", message)
        return run_git(self.path, "rev-parse", "HEAD")


def plugin_source(url, sha=None):
    source = {"source": "url", "url": str(url)}
    if sha is not None:
        source["sha"] = sha
    return source


def claude_plugin(name, url, sha, version="1.2.3"):
    return {"name": name, "version": version, "source": plugin_source(url, sha)}


def codex_plugin(name, url, sha=None):
    return {"name": name, "source": plugin_source(url, sha)}


class CatalogAlignmentTest(unittest.TestCase):
    def test_matching_catalogs_accept_the_same_pinned_source(self):
        claude = [claude_plugin("handoff", "https://example.invalid/handoff.git", "a" * 40)]
        codex = [codex_plugin("handoff", "https://example.invalid/handoff.git", "a" * 40)]

        self.assertEqual(CHECK_PINS.catalog_alignment_problems(claude, codex), [])

    def test_every_coordinate_drift_is_reported(self):
        claude = [
            claude_plugin("handoff", "https://example.invalid/handoff.git", "a" * 40),
            claude_plugin("showme", "https://example.invalid/showme.git", "b" * 40),
        ]
        codex = [
            codex_plugin("showme", "https://elsewhere.invalid/showme.git", "c" * 40),
            codex_plugin("handoff", "https://example.invalid/handoff.git", "a" * 40),
        ]
        codex[1]["source"]["source"] = "git"

        self.assertEqual(
            CHECK_PINS.catalog_alignment_problems(claude, codex),
            [
                "catalog plugin names/order differ: Claude Code has ['handoff', 'showme']; "
                "Codex has ['showme', 'handoff']",
                "handoff: Claude Code and Codex source types differ",
                "showme: Claude Code and Codex repository URLs differ",
                "showme: Claude Code and Codex pinned SHAs differ",
            ],
        )


class SourceValidationTest(unittest.TestCase):
    def test_rejects_untrusted_sources_before_invoking_git(self):
        url = "https://github.com/example/showme.git"
        sha = "a" * 40
        cases = [
            ("Claude Code", None, "source must be an object"),
            ("Claude Code", {"source": "git", "url": url, "sha": sha}, "source type must be url"),
            ("Claude Code", plugin_source("http://github.com/example/showme.git", sha), "source URL"),
            ("Claude Code", plugin_source("https://user@github.com/example/showme.git", sha), "source URL"),
            ("Claude Code", plugin_source("https://github.com.evil/example/showme.git", sha), "source URL"),
            ("Claude Code", plugin_source("https://github.com/example/showme", sha), "source URL"),
            ("Claude Code", plugin_source(f"{url}?ref=main", sha), "source URL"),
            ("Claude Code", plugin_source(url), "full lowercase 40-character sha"),
            ("Claude Code", plugin_source(url, "A" * 40), "full lowercase 40-character sha"),
            ("Codex", plugin_source(url), "full lowercase 40-character sha"),
            ("Codex", {**plugin_source(url), "sha": None}, "full lowercase 40-character sha"),
        ]

        for host, bad_source, expected in cases:
            with self.subTest(host=host, expected=expected):
                claude = claude_plugin("showme", url, sha)
                codex = codex_plugin("showme", url, sha)
                if host == "Claude Code":
                    claude["source"] = bad_source
                else:
                    codex["source"] = bad_source

                with patch.object(CHECK_PINS, "run") as run:
                    problem = CHECK_PINS.check(claude, codex)

                self.assertIn(expected, problem)
                run.assert_not_called()


class GitProcessTest(unittest.TestCase):
    def test_run_disables_prompts_and_applies_a_bounded_timeout(self):
        timeout = subprocess.TimeoutExpired(["git", "clone"], CHECK_PINS.GIT_TIMEOUT_SECONDS)
        with patch.object(CHECK_PINS.subprocess, "run", side_effect=timeout) as subprocess_run:
            with self.assertRaisesRegex(CHECK_PINS.GitTimeoutError, "timed out after 60 seconds"):
                CHECK_PINS.run(["git", "clone"])

        kwargs = subprocess_run.call_args.kwargs
        self.assertEqual(kwargs["timeout"], CHECK_PINS.GIT_TIMEOUT_SECONDS)
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

    def test_check_turns_a_git_timeout_into_a_clear_plugin_error(self):
        url = "https://github.com/example/showme.git"
        sha = "a" * 40
        claude = claude_plugin("showme", url, sha)
        codex = codex_plugin("showme", url, sha)

        with patch.object(
            CHECK_PINS,
            "run",
            side_effect=CHECK_PINS.GitTimeoutError("git operation timed out after 60 seconds"),
        ):
            problem = CHECK_PINS.check(claude, codex)

        self.assertEqual(problem, "showme: git operation timed out after 60 seconds")


class PinCheckTest(unittest.TestCase):
    def make_repository(self, *, claude=None, codex=None):
        repository = PluginRepository(self)
        if claude is None:
            claude = {"name": "showme", "version": "1.2.3"}
        repository.write_manifest("claude", claude)
        if codex is not None:
            repository.write_manifest("codex", codex)
        return repository

    def check(self, repository, sha):
        claude = claude_plugin("showme", repository.path, sha)
        codex = codex_plugin("showme", repository.path, sha)
        with patch.object(CHECK_PINS, "source_problem", return_value=None):
            return CHECK_PINS.check(claude, codex)

    def test_matching_pinned_claude_and_codex_manifests_pass(self):
        repository = self.make_repository(codex={"name": "showme", "version": "1.2.3"})
        sha = repository.commit()

        output = io.StringIO()
        with redirect_stdout(output):
            problem = self.check(repository, sha)

        self.assertIsNone(problem)
        self.assertIn("Claude Code and Codex 1.2.3 match", output.getvalue())

    def test_clone_and_missing_commit_fail_before_manifest_checks(self):
        claude = claude_plugin("showme", "/definitely/not/a/plugin/repository", "a" * 40)
        codex = codex_plugin("showme", "/definitely/not/a/plugin/repository", "a" * 40)
        with patch.object(CHECK_PINS, "source_problem", return_value=None):
            self.assertIn(
                "cannot clone",
                CHECK_PINS.check(claude, codex),
            )

        repository = self.make_repository(codex={"name": "showme", "version": "1.2.3"})
        repository.commit()
        missing_commit = "0" * 40
        self.assertIn(
            "does not exist",
            self.check(repository, missing_commit),
        )

    def test_pinned_codex_manifest_errors_are_rejected(self):
        cases = [
            (None, "no .codex-plugin/plugin.json"),
            ("not json", "is not valid JSON"),
            (["not", "an", "object"], "is not a JSON object"),
            ({"name": "wrong-name", "version": "1.2.3"}, "declares wrong-name"),
            ({"name": "showme", "version": "9.9.9"}, "declares 9.9.9"),
        ]

        for codex_manifest, expected in cases:
            with self.subTest(expected=expected):
                repository = self.make_repository(codex=codex_manifest)
                sha = repository.commit()

                self.assertIn(expected, self.check(repository, sha))

    def test_claude_manifest_name_is_checked_before_codex(self):
        repository = self.make_repository(
            claude={"name": "wrong-name", "version": "1.2.3"},
            codex={"name": "showme", "version": "1.2.3"},
        )
        sha = repository.commit()

        self.assertIn("Claude manifest", self.check(repository, sha))
        self.assertIn("declares wrong-name", self.check(repository, sha))

    def test_claude_manifest_read_errors_fail_before_codex_checks(self):
        cases = [
            (None, "no .claude-plugin/plugin.json"),
            ("not json", "is not valid JSON"),
            (["not", "an", "object"], "is not a JSON object"),
        ]

        for claude_manifest, expected in cases:
            with self.subTest(expected=expected):
                repository = self.make_repository(codex={"name": "showme", "version": "1.2.3"})
                if claude_manifest is None:
                    repository.remove_manifest("claude")
                else:
                    repository.write_manifest("claude", claude_manifest)
                sha = repository.commit()

                self.assertIn(expected, self.check(repository, sha))

    def test_claude_manifest_version_is_checked_before_codex(self):
        repository = self.make_repository(
            claude={"name": "showme", "version": "9.9.9"},
            codex={"name": "showme", "version": "1.2.3"},
        )
        sha = repository.commit()

        self.assertIn("this catalog says 1.2.3", self.check(repository, sha))
        self.assertIn("declares 9.9.9", self.check(repository, sha))


class MainTest(unittest.TestCase):
    def setUp(self):
        self.claude = [claude_plugin("handoff", "https://example.invalid/handoff.git", "a" * 40)]
        self.codex = [codex_plugin("handoff", "https://example.invalid/handoff.git", "a" * 40)]

    def run_main(self, args, *, alignment=None, check_result=None):
        stderr = io.StringIO()
        stdout = io.StringIO()
        with (
            patch.object(CHECK_PINS, "load_plugins", side_effect=[self.claude, self.codex]),
            patch.object(CHECK_PINS, "catalog_alignment_problems", return_value=alignment or []),
            patch.object(CHECK_PINS, "check", return_value=check_result) as check,
            patch.object(sys, "argv", ["check_pins.py", *args]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = CHECK_PINS.main()
        return status, stdout.getvalue(), stderr.getvalue(), check

    def test_main_stops_before_network_checks_when_catalogs_drift(self):
        status, _, stderr, check = self.run_main([], alignment=["source drift"])

        self.assertEqual(status, 1)
        self.assertIn("::error::source drift", stderr)
        check.assert_not_called()

    def test_main_rejects_an_unknown_plugin_filter(self):
        status, _, stderr, check = self.run_main(["showme"])

        self.assertEqual(status, 2)
        self.assertIn("no such plugin in the catalog: showme", stderr)
        check.assert_not_called()

    def test_main_filters_both_catalogs_before_alignment_checks(self):
        showme_sha = "b" * 40
        self.claude.append(
            claude_plugin("showme", "https://example.invalid/showme.git", showme_sha)
        )
        self.codex = [
            codex_plugin("handoff", "https://example.invalid/drifted-handoff.git", "c" * 40),
            codex_plugin("showme", "https://example.invalid/showme.git", showme_sha),
        ]
        stderr = io.StringIO()
        stdout = io.StringIO()
        with (
            patch.object(CHECK_PINS, "load_plugins", side_effect=[self.claude, self.codex]),
            patch.object(CHECK_PINS, "check", return_value=None) as check,
            patch.object(sys, "argv", ["check_pins.py", "showme"]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = CHECK_PINS.main()

        self.assertEqual(status, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("All 1 plugin sources passed", stdout.getvalue())
        checked_claude, checked_codex = check.call_args.args
        self.assertEqual(checked_claude["name"], "showme")
        self.assertEqual(checked_codex["name"], "showme")

    def test_main_reports_check_failures_and_success(self):
        status, _, stderr, check = self.run_main(["handoff"], check_result="manifest mismatch")
        self.assertEqual(status, 1)
        self.assertIn("1 of 1 entries are out of step", stderr)
        check.assert_called_once()

        status, stdout, stderr, check = self.run_main([])
        self.assertEqual(status, 0)
        self.assertIn("All 1 plugin sources passed", stdout)
        self.assertEqual(stderr, "")
        check.assert_called_once()


if __name__ == "__main__":
    unittest.main()
