# 3. Enrich calls with a Chain of Responsibility, export with Observers

- Status: accepted
- Date: 2026-10-13

## Context
After a call completes, several independent steps are needed: normalise the provider response, estimate missing tokens, price the call, classify errors, sanitise content. The steps depend on each other's output (cost needs tokens) and users need to add their own (e.g. a custom PII rule) or reorder them. Separately, the enriched record must reach several destinations (spans, metrics, logs, budget alerts).

## Decision
- **Enrichment**: a Chain of Responsibility of `Processor`s. Each handler decides whether it applies (`applies_to`) and always forwards, so the chain behaves as a configurable pipeline whose order expresses dependencies.
- **Export**: an `EventBus` (Observer) publishing `CallStarted` / `CallFinished` to independent `Subscriber`s.
- **Isolation**: exceptions in a processor or subscriber are logged and swallowed; the instrumented application call is never affected.

## Alternatives considered
- A single monolithic `record()` function: simplest, but every new concern edits the same code.
- OpenTelemetry `SpanProcessor`s only: would tie enrichment to tracing and leave metrics and alerts without the computed cost.

## Consequences
Adding a concern is adding a class. The price is indirection: the effective behaviour depends on chain order, which is why the default order is defined in one place (`default_chain`).
