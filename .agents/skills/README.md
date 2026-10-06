# AlphaMaxxin research skills

This directory versions the ten Codex research skills adapted from the
Alpha Maxxin analysis prompt library. Each skill includes its instructions,
agent metadata, and any supporting references or scripts.

Open the repository in Codex and select a skill by name, for example:

- `$alpha-macro Explain how weaker US payrolls change the Fed's policy trade-off.`
- `$alpha-fundamentals Compare these companies over the next 6–12 months.`
- `$alpha-research Build a sourced investment thesis for this asset and horizon.`

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

These instructions support research in Codex. They are separate from the
application's Python skills and do not automatically configure its analyst lenses.

## Offline signal calculator

The synthesis skill includes a standard-library calculator for supplied JSON:

```sh
python .agents/skills/alpha-signal-synthesis/scripts/aggregate_signals.py --help
python .agents/skills/alpha-signal-synthesis/scripts/aggregate_signals.py inputs.json
```

See its [methodology](alpha-signal-synthesis/references/weights-and-overrides.md)
for the input schema and calculation rules. The calculator reads supplied
scores; it does not retrieve data or verify the underlying evidence.

Run its offline regression tests from the repository root:

```sh
python -m unittest discover -s backend/tests -p test_analysis_skill_synthesis.py
```

The same tests are collected by the normal backend pytest suite.
