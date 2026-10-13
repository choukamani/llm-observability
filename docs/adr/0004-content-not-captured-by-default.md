# 4. Do not export prompts and completions by default

- Status: accepted
- Date: 2026-10-13

## Context
Prompts and completions routinely contain personal or confidential data. Telemetry backends usually have wider access and longer retention than the application database.

## Decision
`ContentPolicy` is the last link of the chain and drops content unless `capture_content=True`. When enabled, emails, card-like numbers and phone numbers are redacted with regular expressions and text is truncated (1 000 characters by default). Token estimation runs *before* the policy, so it still has the text.

## Consequences
Safe default, compatible with GDPR data-minimisation. Regex redaction is best-effort: it does not detect names or addresses. Teams with stricter needs should plug in an NER-based processor or keep content capture off.
