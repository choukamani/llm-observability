# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-13

### Added
- `Instrumentor` facade with `track()` context manager, `observe()` decorator (sync and async) and `InstrumentedChatClient` wrapper.
- Processing chain: response normalisation (OpenAI, Azure OpenAI, Mistral, Ollama), token estimation, cost estimation from a versioned price table, error classification, content policy with PII redaction.
- Event bus with OpenTelemetry span and metric sinks (GenAI semantic conventions), JSON logging sink and per-tenant budget alerts.
- Request-scoped attributes via `contextvars`.
- FastAPI demo, traffic generator and docker-compose stack (OTel Collector, Prometheus, Tempo, Grafana) with a provisioned dashboard.
- Overhead benchmark, ADRs 1–5, CI workflow.
