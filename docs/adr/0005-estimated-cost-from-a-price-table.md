# 5. Estimate cost locally from a versioned price table

- Status: accepted
- Date: 2026-10-13

## Context
Providers do not return the price of a call. Cost per tenant and per feature is nevertheless the metric product teams ask for first.

## Decision
Ship a TOML price table (USD per million tokens) with an `as_of` date and its sources; resolve models by exact key, then longest prefix (dated snapshots such as `gpt-4o-mini-2024-07-18`), then a `provider/*` wildcard. Unknown models get **no** cost rather than a guessed one. Applications can load their own table.

## Consequences
Cost is always labelled *estimated*. It drifts when providers change prices, discounts, cached-token or batch pricing are not modelled, and should be reconciled with invoices. Budget alerts built on it are early warnings, not accounting.
