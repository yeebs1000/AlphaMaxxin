# AlphaMaxx research skills

Ten standalone research skills for **Codex and Claude Code**, adapted from
the Alpha Maxxin analysis prompt library. Each folder contains the instructions
and the references or scripts needed for its domain. They run in your existing
assistant; installing the AlphaMaxxin application is unnecessary.

## Install

Paste this request into Codex or Claude Code:

```text
Install the AlphaMaxx research skills for this assistant by following:
https://raw.githubusercontent.com/yeebs1000/AlphaMaxxin/master/INSTALL_SKILLS.md
```

Or download the [skills-only ZIP](https://github.com/yeebs1000/AlphaMaxxin/releases/download/skills-v0.1.0/alphamaxx-skills.zip).
The [installation guide](https://github.com/yeebs1000/AlphaMaxxin/blob/master/INSTALL_SKILLS.md)
covers both clients, the Claude Code plugin, and individual skill folders.

## Use

In Codex, select a skill by name, for example:

- `$alpha-macro Explain how weaker US payrolls change the Fed's policy trade-off.`
- `$alpha-fundamentals Compare these companies over the next 6–12 months.`
- `$alpha-research Build a sourced investment thesis for this asset and horizon.`

In the Claude Code plugin, use `/alphamaxx-research:alpha-macro` or
`/alphamaxx-research:alpha-research`. Plain personal skill folders use
`/alpha-macro` and `/alpha-research`.

| Skill | Purpose |
| --- | --- |
| [alpha-research](alpha-research/SKILL.md) | Coordinate a full investment research thesis. |
| [alpha-macro](alpha-macro/SKILL.md) | Economic cycles, central banks, and regional conditions. |
| [alpha-rates-fx-commodities](alpha-rates-fx-commodities/SKILL.md) | Rates, credit, currencies, and commodities. |
| [alpha-fundamentals](alpha-fundamentals/SKILL.md) | Company financials, valuation, and sector economics. |
| [alpha-technicals-liquidity](alpha-technicals-liquidity/SKILL.md) | Trends, momentum, positioning, and liquidity. |
| [alpha-alternative-data](alpha-alternative-data/SKILL.md) | Alternative datasets, sentiment, and disclosed transactions. |
| [alpha-catalysts-capital](alpha-catalysts-capital/SKILL.md) | Events, financing, and corporate transactions. |
| [alpha-quant-validation](alpha-quant-validation/SKILL.md) | Models, backtests, and statistical validation. |
| [alpha-signal-synthesis](alpha-signal-synthesis/SKILL.md) | Combine signals for a specific asset and horizon. |
| [alpha-portfolio-risk](alpha-portfolio-risk/SKILL.md) | Allocations, stress scenarios, exposures, and hedges. |

Research must distinguish dated evidence from assumptions, identify unavailable
data, and map each signal to the asset and investment horizon. Confidence
multipliers describe evidence quality, rather than calibrated probabilities.

These are research instructions, separate from the application's Python
analytics and analyst lenses. They do not ship market feeds, establish an
investment edge, or validate an assistant's conclusions automatically. Evidence
access depends on your assistant's available tools and the sources you provide.

## Offline signal calculator

The synthesis skill includes a standard-library calculator for supplied JSON:

```sh
python "<installed-skill-path>/scripts/aggregate_signals.py" --help
python "<installed-skill-path>/scripts/aggregate_signals.py" "<input-path>.json"
```

See its [methodology](alpha-signal-synthesis/references/weights-and-overrides.md)
for the input schema and calculation rules. The calculator reads supplied
scores; it does not retrieve data or verify the underlying evidence.

The optional calculator uses Python 3 and its standard library. It runs from
any working directory when given absolute script and input paths.

For contributors with the **full repository**, run the offline regressions:

```sh
python -m unittest discover -s backend/tests -p test_analysis_skill_synthesis.py
```

The same tests are collected by the normal backend pytest suite.
The standalone ZIP includes the calculator, not the application's test tree.

## Provenance and license

The instructions condense the original Alpha Maxxin research prompt library.
References to its illustrative thresholds describe assumptions to assess,
rather than default trading rules. The suite is licensed under [MIT](LICENSE).
