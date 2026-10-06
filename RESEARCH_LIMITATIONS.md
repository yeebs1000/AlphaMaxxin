# Current research and product limitations

AlphaMaxxin is an experimental local research workbench. Its offline tests
demonstrate software behavior against fixtures; they do not establish an
investment edge or reliable live research outcomes. The standalone skills
provide analytical guidance and do not independently enforce these standards.

## Signals and allocation

[Signal weights and allocation tiers](backend/app/skills/signals.py) are
heuristics. Full/Half/Starter currently map to 5%/3%/1.5%, with targets based
on ATR or analyst consensus. These are not calibrated probabilities or
portfolio-specific optimal allocations. The
[event-study backtest](backend/app/skills/backtest.py) excludes portfolio sizing,
transaction costs, and netting of overlapping positions.

## AI output checks

The [synthesis prompt](backend/app/llm/prompts/synthesis.md) asks the model to
respect supplied numbers, red-line vetoes, and conviction conditions. The
[response parser](backend/app/llm/analysts.py) currently accepts a response with
nonempty Markdown and passes through its recommendations. It does not fully
validate those recommendations against the computed input contract.

An offline fake-response check confirmed that a buy/high/Full recommendation
with an invented target could be accepted even when supplied inputs specified
a Pass tier and a distress veto. A generated report therefore requires checking
against its sources and computed inputs. Prompt instructions alone do not
provide an enforced numeric or risk boundary.

## ML evaluation

The [trainer](scripts/train_ml_alpha.py) uses overlapping 60-day forward-return
labels with `TimeSeriesSplit` and no label-window purge or gap. Training outcome
windows can overlap the subsequent test period. Its pooled panel also needs
splits that preserve complete dates, and its fixed current ticker universe does
not reconstruct historical index membership.

Current FRED histories with a uniform publication delay do not reconstruct
historical unrevised data vintages. Stored accuracy and AUC do not establish
probability calibration or net investment performance. Treat ML outputs as
experimental until evaluation addresses these issues with point-in-time data,
purged splits, costs, baselines, and held-out performance.

## Installation and live use

The [setup wizard](setup.py) installs Python packages into its current
interpreter and installs optional integrations together. Most Python
dependencies remain unbounded. An isolated environment is preferable for
development; passing CI reflects the versions resolved for that run.

Default report models are Gemini. A user who configures only an OpenAI or
Anthropic key must choose matching models in Settings before generating AI
reports; the wizard does not currently make that selection automatically.
The wizard also does not currently stop after frontend install/build failures.

The repository has no complete checked-in demo report or demo dataset. CI
builds the frontend but does not exercise browser journeys. Offline checks do
not verify real broker gateways, provider uptime, model responses, or the full
new-user experience.

The most useful next improvements are a reproducible demo, isolated reliable
setup, enforced output contracts, browser workflow tests, and stronger ML
evaluation. Adding more features does not address those gaps.
