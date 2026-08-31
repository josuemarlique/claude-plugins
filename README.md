# claude-plugins

The plugin catalog for [Claude Code](https://docs.claude.com/en/docs/claude-code) and Codex.

This repository holds **no plugin code**.
It is a list.
Each plugin lives in its own repository, and this file points at an exact commit in each one.

## Install

Add the catalog once, then install whatever you want from it:

```
/plugin marketplace add josuemarlique/claude-plugins
/plugin install handoff@jmarlique-tools
/plugin install showme@jmarlique-tools
```

In Codex:

```
codex plugin marketplace add josuemarlique/claude-plugins
codex plugin add handoff@jmarlique-tools
```

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

Every entry pins an exact commit, so a new version takes two steps:

1. Push the change in the plugin's own repository.
2. Update that entry's `sha`, and its `version` if it changed, in `.claude-plugin/marketplace.json` here.

Step 2 is easy to forget and fails silently: without it, everyone keeps installing the old commit and nothing reports a problem.
CI guards it.
On every push, and once a week on a schedule, it clones each pinned commit and fails if the commit is missing or if the version the plugin actually declares disagrees with the version listed here.

Then, on each machine:

```
/plugin marketplace update jmarlique-tools
```

That refreshes the catalog and the plugins installed from it in one step.

## Moved here from the handoff repository

This catalog used to live inside `josuemarlique/handoff`, which was fine while that repo shipped the only plugin.
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
python3 -m unittest discover -s tests -t .   # the file itself is well formed
python3 scripts/check_pins.py                # each pin resolves and matches (needs network)
```

`check_pins.py` takes plugin names too, so `python3 scripts/check_pins.py showme` checks just one.

## License

MIT - see [LICENSE](LICENSE).
Each plugin carries its own license in its own repository.
