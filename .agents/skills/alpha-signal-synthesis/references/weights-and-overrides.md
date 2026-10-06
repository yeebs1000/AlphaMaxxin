# Weights and overrides

## Optional source profile (21 channels, sum 100%)

| Channel | Weight % |
|---|---:|
| Fundamental | 18 |
| US macro | 13 |
| Technical | 13 |
| Fixed income/rates | 8 |
| China | 8 |
| Japan | 5 |
| Korea | 4 |
| Alternative data | 4 |
| ML alpha | 4 |
| Political disclosures | 4 |
| APAC ex-China/Japan/Korea | 3 |
| EM ex-China | 3 |
| EMEA/other developed | 2 |
| FX/commodities | 2 |
| Sector | 2 |
| Central-bank text | 2 |
| Order book/liquidity | 1 |
| Supply chains | 1 |
| Developer momentum | 1 |
| IPO | 1 |
| Private capital | 1 |

This is a source convention, not fitted weights or a validated allocation. Social sentiment and catalysts are not weighted in the source despite appearing in horizon descriptions; use them as contextual inputs or explicitly define an alternative model. Do not silently add them or count the same data twice.

## Conflicts requiring an explicit model choice

- Prompt 0 flags all >1.5 divergences; Prompt 23 restricts this to weights >=5%. Prefer transparent reporting of material disagreements.
- Prompt 23 risk-off conflict handling halves fundamental/ML weights and reallocates the remainder; its separate override adds 5 percentage points to technical/order-book and subtracts 10 from fundamental. Do not stack these variants silently. Risk-off conditions need dated VIX and an explicitly defined credit-widening window.
- Political boost: Prompt 14b needs positive technical/fundamental plus >$100,000 accumulation; Prompt 23 needs political>1.5 and fundamental>1.0. No automatic default. Evaluate disclosure timing and incremental out-of-sample contribution before considering either.
- China score cap -1, JPY carry deduction -0.5, and gold/long-vol boost +1 are heuristic research scenarios. A regulatory assessment does not force a particular return direction; a hedge's cost and basis matter.
- Taiwan hedge trigger differs between >=3 portfolio/consolidated rules and >=4 score overlay. Define a documented rubric and distinguish review versus action triggers.
- Positive modifiers can push scores outside [-2,+2]. Show raw output, clip final values, and apply any explicitly configured upper risk cap last.

## Calculator input

```json
{
  "asset": "EXAMPLE", "horizon": "positional",
  "inputs": [
    {"name": "fundamental", "asset": "EXAMPLE", "horizon": "positional", "weight": 18, "score": 1.2, "confidence": "High", "direction_mapped": true},
    {"name": "technical", "asset": "EXAMPLE", "horizon": "positional", "weight": 13, "score": -0.5, "confidence": "Medium", "direction_mapped": true},
    {"name": "other eligible evidence", "asset": "EXAMPLE", "horizon": "positional", "weight": 69, "score": null}
  ]
}
```

Weights can be percent or fractions if consistent. Include unavailable eligible inputs with null scores so coverage is measured against the complete chosen universe. Optional `adjustments` is a list of `{ "reason": "explicitly selected scenario", "delta": 0.5 }`; optional `upper_cap` is in [-2,+2]. These are arithmetic inputs, not empirically authorized rules. Do not provide them unless a rule or scenario was explicitly selected. Calculator accepts only tactical/positional/thematic and emits JSON to stdout.

If a request supplies numerical scores without asset/horizon identifiers, show an arithmetic demonstration only under an explicitly stated hypothetical common target; do not call it a valid target-specific composite. The output `available_input_confidence_multiplier` averages supplied confidence multipliers over available base weights; it is neither overall research confidence nor probability. Judge evidence freshness, missing-weight coverage and dependence separately.
