# 2. Emit OpenTelemetry using the GenAI semantic conventions

- Status: accepted
- Date: 2026-10-13

## Context
LLM calls must be visible next to the rest of an application's telemetry (HTTP, DB) and portable across backends (Grafana, Datadog, Google Cloud Monitoring...). Vendor SDKs (LangSmith, Langfuse...) give rich LLM views but create a second, separate telemetry silo.

## Decision
Export only through the OpenTelemetry API, using the GenAI semantic conventions (`gen_ai.client.operation.duration`, `gen_ai.client.token.usage`, `gen_ai.provider.name`, `gen_ai.usage.*`). Concepts the conventions do not cover (estimated cost, in-flight calls, estimated-token flag) use an `llm.` namespace.

## Consequences
- Any OTLP backend works unchanged; spans nest under the application's HTTP spans automatically.
- The GenAI conventions are still marked *development*: attribute names may change (e.g. `gen_ai.system` became `gen_ai.provider.name`). Names are centralised in `sinks/otel.py` so a rename is a one-file change.
- Rich LLM-specific UIs (prompt playgrounds, evaluations) are out of scope.
