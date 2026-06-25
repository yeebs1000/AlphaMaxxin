# tests/

These are manual smoke-test scripts, not an automated suite, and they are
**not run in CI**:

- `test_cli.py` invokes the real agent pipeline (`runner.run_agent()`), which
  calls a paid LLM API. Running it costs real money per invocation.
- `test_news.py` calls live Finnhub/Alpha Vantage news APIs and requires a
  populated `.env` at the repo root.

Run them yourself, deliberately, from the repo root:

```
python tests/test_cli.py "China Market Agent"
python tests/test_news.py
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidance on testing changes
without burning API calls.
