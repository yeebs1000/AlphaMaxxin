# Install AlphaMaxx research skills

Ten standalone research skills for **Codex and Claude Code**. Use them without
installing the AlphaMaxxin app, Node.js, broker software, or provider SDKs.
The instructions need no API keys of their own. Your assistant's normal model
access and any research sources you choose still apply. The optional signal
calculator uses Python 3 and its standard library.

These skills organize evidence and research reasoning. They do not supply data,
verify sources automatically, or establish profitable investment performance.

## Paste this into your assistant

```text
Install the AlphaMaxx research skills for this assistant by following:
https://raw.githubusercontent.com/yeebs1000/AlphaMaxxin/master/INSTALL_SKILLS.md
```

The link is an installation guide; pasting a URL alone may only open it. Include
the installation request above.

## Instructions for the assistant doing the install

Identify the current client from the session. Install only the research skills
for that client, at user scope unless the user requests a project installation.
Use an existing destination when the client supplies one; otherwise use the
documented locations below. Resolve home paths for the user's OS. Check for
existing `alpha-*` folders before copying and preserve existing versions unless
the user authorizes replacement. Do not run the app setup wizard or configure
brokers, API keys, hooks, or MCP servers as part of this installation.

### Codex

Use the bundled `$skill-installer` when it is available. Install from repository
`yeebs1000/AlphaMaxxin`, ref `skills-v0.1.0`, using these paths:

```text
.agents/skills/alpha-research
.agents/skills/alpha-macro
.agents/skills/alpha-rates-fx-commodities
.agents/skills/alpha-fundamentals
.agents/skills/alpha-technicals-liquidity
.agents/skills/alpha-alternative-data
.agents/skills/alpha-catalysts-capital
.agents/skills/alpha-quant-validation
.agents/skills/alpha-signal-synthesis
.agents/skills/alpha-portfolio-risk
```

The helper accepts multiple `--path` values and `--ref skills-v0.1.0`. Set
`--dest` to the client's supported absolute skills directory; current Codex
documents `~/.agents/skills` for personal skills. Keep each skill's supporting
files and its MIT `LICENSE`. For project scope, use `<project>/.agents/skills`.

If the bundled installer is unavailable, use the ZIP method below. Confirm the
ten `SKILL.md` files exist and start a new turn; restart the client if discovery
does not update. Invoke `$alpha-research` or `$alpha-macro`.

### Claude Code

For current Claude Code, use its native plugin installer. The marketplace
downloads the small skills archive rather than installing the application:

```sh
claude plugin marketplace add https://raw.githubusercontent.com/yeebs1000/AlphaMaxxin/master/.claude-plugin/marketplace.json
claude plugin install alphamaxx-research@alphamaxx
claude plugin list
```

The archive source requires Claude Code 2.1.224 or newer. Inside a session,
`/plugin marketplace add <the-marketplace-URL>` and
`/plugin install alphamaxx-research@alphamaxx` expose the native plugin UI.
Invoke `/alphamaxx-research:alpha-research` or
`/alphamaxx-research:alpha-macro`. Reload plugins or start a new session if
the commands are not visible yet.

For older clients or plain skill folders, use the ZIP method and install into
`~/.claude/skills`; project scope uses `<project>/.claude/skills`. Plain folders
are invoked as `/alpha-research` and `/alpha-macro`.

### ZIP download for either client

Download [alphamaxx-skills.zip](https://github.com/yeebs1000/AlphaMaxxin/releases/download/skills-v0.1.0/alphamaxx-skills.zip)
and [SHA256SUMS](https://github.com/yeebs1000/AlphaMaxxin/releases/download/skills-v0.1.0/SHA256SUMS).
Verify the archive's SHA-256 against the checksum before extracting.

Copy the ten top-level `alpha-*` directories to the chosen skills directory,
preserving `SKILL.md`, `references/`, `scripts/`, and `agents/` inside each.
Keep the included MIT `LICENSE` with the distributed files. The ZIP also holds
plugin metadata and this guide; those do not need to be copied into each
personal skill folder.

Report the installed locations, any existing folders skipped, and the correct
invocation for the current client. Installing files does not demonstrate the
quality of a subsequent investment analysis.

## First use

Try one focused request before asking for a full thesis:

```text
Use alpha-macro to explain how weak US payrolls and persistent inflation
change the Fed's policy trade-off. Separate the conditions for a hold,
a hike, and a cut; cite current primary sources if browsing is available.
```

See the [skill catalog](https://github.com/yeebs1000/AlphaMaxxin/tree/master/.agents/skills)
for the ten domains. Research instructions and the application's Python
analytics are maintained separately.

Installation conventions follow the official
[Codex skills documentation](https://learn.chatgpt.com/docs/build-skills),
[Claude Code skills documentation](https://code.claude.com/docs/en/skills),
and [Claude Code marketplace documentation](https://code.claude.com/docs/en/plugin-marketplaces).
