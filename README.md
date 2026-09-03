# claude-plugins

The plugin catalog for [Claude Code](https://docs.claude.com/en/docs/claude-code) and Codex.

This repository holds **no plugin code**.
It is a list.
Each plugin lives in its own repository, and every entry points at an exact commit.

## Install

Add the catalog once, then install whatever you want from it:

### Claude Code

```
/plugin marketplace add josuemarlique/claude-plugins
/plugin install handoff@jmarlique-tools
/plugin install showme@jmarlique-tools
```

### Codex CLI

```
codex plugin marketplace add josuemarlique/claude-plugins
codex plugin add handoff@jmarlique-tools
codex plugin add showme@jmarlique-tools
```

Start a new Codex thread after installing so it loads the new plugin skills.

### Why the two names differ

`josuemarlique/claude-plugins` is the **repository** the list is fetched from.
`jmarlique-tools` is the **name the list gives itself**, which is why it is the part after the `@`.
They do not have to match, and here they do not.

## What is in it

| Plugin | What it does | Repository |
| --- | --- | --- |
| `handoff` | Ends a session with a written record so the next one picks up where it left off, losing nothing. | [josuemarlique/handoff](https://github.com/josuemarlique/handoff) |
| `showme` | Opens agent-generated HTML in a local browser so you can point at what needs changing and send that back, instead of reading a wall of text. | [josuemarlique/showme](https://github.com/josuemarlique/showme) |

## Updating a plugin

Every entry pins an exact commit, so a new version takes three steps:

1. Push the change in the plugin's own repository.
2. Update that entry's `sha`, and its `version` if it changed, in `.claude-plugin/marketplace.json` here.
3. Update the matching `url` and `sha` in `.agents/plugins/marketplace.json` here.

The two catalogs deliberately duplicate only the source coordinates each host needs.
Their tests require repository URLs, plugin order, and pinned SHAs to stay identical.

Steps 2 and 3 are easy to forget and fail silently: without them, one host can keep installing an old commit while the other moves forward.
CI guards it.
On every push, and once a week on a schedule, it clones each pinned commit and fails if the commit is missing or if the version the plugin actually declares disagrees with the version listed here.
For every Codex entry, it also requires that commit to contain the native Codex plugin manifest.

Then refresh the marketplace on each machine.

For Claude Code:

```
/plugin marketplace update jmarlique-tools
```

That refreshes the Claude catalog and the plugins installed from it in one step.

For Codex CLI, upgrade the marketplace snapshot and reinstall whichever plugins changed:

```sh
codex plugin marketplace upgrade jmarlique-tools
codex plugin remove handoff@jmarlique-tools
codex plugin add handoff@jmarlique-tools
codex plugin remove showme@jmarlique-tools
codex plugin add showme@jmarlique-tools
```

Start a new Codex thread afterward so it picks up the updated skills.

## Moved here from the handoff repository

The Claude Code catalog used to live inside `josuemarlique/handoff`, which was fine while that repo shipped the only plugin.
Once it listed a second one, adding a marketplace called "handoff" to install something else was confusing, and shipping that other plugin meant committing to the handoff repository.

The marketplace name is unchanged, so `handoff@jmarlique-tools` still resolves.
Only the repository you add it from moved.
If you added the old one, switch over once per machine:

```
/plugin marketplace remove jmarlique-tools
/plugin marketplace add josuemarlique/claude-plugins
```

## Checks

```sh
python3 -m unittest discover -s tests -t .   # both catalog files are well formed and aligned
python3 scripts/check_pins.py                # each pin and both host manifests match (needs network)
```

`check_pins.py` takes plugin names too, so `python3 scripts/check_pins.py showme` checks just one.

## License

MIT - see [LICENSE](LICENSE).
Each plugin carries its own license in its own repository.
