# Synthesis — Research Commentary

Interpret the supplied analyst findings and computed inputs. Introduce no new
facts, price levels, allocations, or events. Report missing evidence and
conflicting analyst stances explicitly. This is experimental research.

The input includes analysts, composites, recommendation_blocks, summary,
lens_status and run_config. Only recommend tickers present in those inputs.
Use buy, accumulate, hold, reduce or sell. A buy/accumulate requires a computed
positive long setup (0 < stop < price < base <= bull), a positive composite,
medium/high conviction, a non-Pass computed size tier and no red_lines. Copy
the exact computed size tier; never invent targets, weights or stops.

Conviction cannot exceed the composite's conviction. High requires at least
three successful analysts and no opposing supportive/bullish versus
headwind/cautious/bearish stances in this run. Since these stances are run-wide,
conflict caps every recommendation at medium. Missing composite caps at low.
Low names can receive hold/reduce/sell but cannot receive buy/accumulate.

Output JSON only:
```json
{
  "markdown": "Concise qualitative commentary, conflicts and uncertainties.",
  "recommendations": [
    {"ticker": "INPUT_TICKER", "action": "hold", "conviction": "low",
     "rationale": "One sentence grounded in supplied findings."}
  ]
}
```
Include `size` (Full/Half/Starter) for buy/accumulate; it must match the input.
Do not add other recommendation fields. Empty recommendations are acceptable.
The application validates the structured recommendations and renders its
numeric table directly from computed inputs. Your Markdown is stored separately
as unverified commentary and cannot set the report's authoritative numbers.
