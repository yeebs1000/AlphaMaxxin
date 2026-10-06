# Security and data handling

AlphaMaxxin is a personal desktop web app. `python run.py` binds the API to
`127.0.0.1:8000`; use it on your own machine. The API has no user
authentication and includes local portfolio edits and report generation,
which can incur LLM charges. Do not expose it through a public interface,
tunnel, or internet-facing reverse proxy. Hosted or multi-user deployment
is outside the supported setup.

The API accepts only `localhost` and `127.0.0.1` Host names. Requests that
change state reject browser Origins outside the local UI and Vite development
server. Clients without an Origin header remain supported; these checks do
not authenticate local processes.

Security fixes target the current `master` branch. Legacy tags and inactive
research branches are historical snapshots rather than supported releases.

## Broker access

The app's broker clients read positions and market data. They do not place,
modify, or cancel orders or transfer funds. Keep IBKR's Read-Only API option
enabled. Separately installed vendor agent tools can have trading
capabilities; see [Third-party notices](THIRD_PARTY_NOTICES.md).

## Local files and external services

API keys belong in `.env`; Tiger private keys should stay in a local file
referenced by `TIGER_PRIVATE_KEY_PATH`. `.env`, personal portfolio files,
generated reports, and `data_store/` are ignored by Git. This prevents
normal commits from including them; it does not encrypt the files or
prevent explicitly adding them to Git.

Live market queries go to the configured data providers. When you generate
a report with a cloud LLM, the app sends computed report context to that
provider. Portfolio context can include tickers, quantities, cost values,
market values, weights, and derived risk metrics. Provider retention and
processing terms apply. A local model receives this context at the endpoint
address you configure. An MCP client can also receive portfolio details
when it invokes the app's read-only tools.

## Verification and issue reports

Routine tests and CI run offline, with fixtures and mocked providers.
They do not establish that live brokers, data feeds, or LLM services work;
live checks require the operator's credentials and deliberate use. See
[CONTRIBUTING.md](CONTRIBUTING.md).

When reporting a security issue, describe the affected version, behavior,
and reproduction steps. Remove API keys, account identifiers, holdings,
and private reports from logs or screenshots before sharing them. Use the
repository's private vulnerability reporting channel if it is available.
