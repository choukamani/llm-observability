# Contributing

Thanks for your interest! This is a demonstration project, but issues and pull requests are welcome.

## Setup

```bash
uv sync                    # Python 3.12, dev dependencies
uv run pre-commit install  # ruff + mypy on every commit
```

## Before opening a pull request

```bash
make check   # ruff, mypy --strict, pytest with coverage >= 80 %
```

- Keep the public API typed; `mypy --strict` must pass.
- Add tests for every behaviour change. Integration tests live in `tests/integration`.
- Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `ci:`, `chore:`).
- Significant design changes come with an ADR in `docs/adr/`.

## Adding a processor or a sink

- Processor: subclass `llmobs.pipeline.Processor`, implement `process()` (and `applies_to()` if it is conditional), insert it into the chain.
- Sink: any object with `notify(event)`; pass it to `Instrumentor.create(subscribers=[...])`.
