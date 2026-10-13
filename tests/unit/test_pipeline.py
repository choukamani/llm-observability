from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from llmobs.model import CallStatus, ErrorCategory, LLMCall, TokenUsage
from llmobs.pipeline import (
    ContentPolicy,
    CostEstimator,
    ErrorClassifier,
    Processor,
    ResponseNormalizer,
    TokenEstimator,
    build_chain,
)
from llmobs.pricing import ModelPrice, PriceTable


class Tag(Processor):
    def __init__(self, name: str, log: list[str]) -> None:
        super().__init__()
        self.name, self.log = name, log

    def process(self, call: LLMCall) -> None:
        self.log.append(self.name)


def test_chain_runs_handlers_in_order() -> None:
    log: list[str] = []
    head = build_chain([Tag("a", log), Tag("b", log), Tag("c", log)])
    assert head is not None
    head.handle(LLMCall("p", "m"))
    assert log == ["a", "b", "c"]


def test_empty_chain() -> None:
    assert build_chain([]) is None


def test_handler_that_does_not_apply_still_forwards() -> None:
    log: list[str] = []
    head = build_chain([TokenEstimator(), Tag("after", log)])
    assert head is not None
    call = LLMCall("p", "m")  # no text: estimator does not apply
    head.handle(call)
    assert call.usage is None
    assert log == ["after"]


def test_normalizer_keeps_requested_model_and_records_response_model() -> None:
    call = LLMCall("openai", "gpt-4o-mini")
    call.response = {"model": "gpt-4o-mini-2024-07-18", "usage": {"prompt_tokens": 1}}
    ResponseNormalizer().handle(call)
    assert call.model == "gpt-4o-mini"
    assert call.response_model == "gpt-4o-mini-2024-07-18"
    assert call.usage == TokenUsage(1, 0)


def test_normalizer_does_not_overwrite_explicit_usage() -> None:
    call = LLMCall("openai", "m", usage=TokenUsage(100, 100))
    call.response = {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    ResponseNormalizer().handle(call)
    assert call.usage == TokenUsage(100, 100)


def test_token_estimator_flags_estimates() -> None:
    call = LLMCall("x", "m", prompt="a" * 10, completion="b" * 3)
    TokenEstimator(chars_per_token=4).handle(call)
    assert call.usage == TokenUsage(3, 1, estimated=True)


def test_token_estimator_rejects_bad_ratio() -> None:
    with pytest.raises(ValueError, match="positive"):
        TokenEstimator(chars_per_token=0)


def test_cost_uses_response_model_with_prefix_match() -> None:
    call = LLMCall("openai", "gpt-4o-mini", usage=TokenUsage(1_000_000, 1_000_000))
    call.response_model = "gpt-4o-mini-2024-07-18"
    CostEstimator().handle(call)
    assert call.cost_usd == pytest.approx(0.15 + 0.60)


def test_unknown_model_has_no_cost() -> None:
    call = LLMCall("openai", "unknown-model", usage=TokenUsage(10, 10))
    CostEstimator().handle(call)
    assert call.cost_usd is None


def test_wildcard_price() -> None:
    call = LLMCall("ollama", "llama3.1:8b", usage=TokenUsage(500, 500))
    CostEstimator().handle(call)
    assert call.cost_usd == 0.0


def test_price_table_from_custom_toml(tmp_path: Path) -> None:
    file = tmp_path / "prices.toml"
    file.write_text('[meta]\nas_of = "2026-01"\n[models."acme/m1"]\ninput = 1\noutput = 2\n')
    table = PriceTable.from_toml(file)
    assert table.as_of == "2026-01"
    assert table.lookup("acme", "m1") == ModelPrice(1.0, 2.0)
    assert PriceTable({}).as_of is None


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError(), ErrorCategory.TIMEOUT),
        (type("E", (Exception,), {"status_code": 429})(), ErrorCategory.RATE_LIMIT),
        (type("E", (Exception,), {"status_code": 401})(), ErrorCategory.AUTHENTICATION),
        (type("E", (Exception,), {"status_code": 504})(), ErrorCategory.TIMEOUT),
        (type("E", (Exception,), {"status_code": 500})(), ErrorCategory.PROVIDER),
        (type("E", (Exception,), {"status_code": 404})(), ErrorCategory.INVALID_REQUEST),
        (type("E", (Exception,), {"status_code": 302})(), ErrorCategory.UNKNOWN),
        (type("RateLimitError", (Exception,), {})(), ErrorCategory.RATE_LIMIT),
        (type("APITimeoutError", (Exception,), {})(), ErrorCategory.TIMEOUT),
        (type("PermissionDeniedError", (Exception,), {})(), ErrorCategory.AUTHENTICATION),
        (type("BadRequestError", (Exception,), {})(), ErrorCategory.INVALID_REQUEST),
        (ValueError("boom"), ErrorCategory.UNKNOWN),
    ],
)
def test_error_classification(error: BaseException, expected: ErrorCategory) -> None:
    assert ErrorClassifier.classify(error) is expected


def test_error_classifier_reads_status_from_http_response() -> None:
    error = Exception()
    error.response = SimpleNamespace(status_code=429)  # type: ignore[attr-defined]
    call = LLMCall("p", "m", status=CallStatus.ERROR, error=error)
    ErrorClassifier().handle(call)
    assert call.error_category is ErrorCategory.RATE_LIMIT


def test_content_dropped_by_default() -> None:
    call = LLMCall("p", "m", prompt="secret", completion="answer")
    ContentPolicy().handle(call)
    assert call.prompt is None
    assert call.completion is None


def test_content_captured_is_redacted_and_truncated() -> None:
    call = LLMCall(
        "p",
        "m",
        prompt="mail jane.doe@example.com, card 4111 1111 1111 1111, tel +33 6 12 34 56 78",
        completion="x" * 50,
    )
    ContentPolicy(capture=True, max_chars=20).handle(call)
    assert call.completion == "x" * 20
    redacted = ContentPolicy.redact(
        "mail jane.doe@example.com, card 4111 1111 1111 1111, tel +33 6 12 34 56 78"
    )
    assert "example.com" not in redacted
    assert "4111" not in redacted
    assert "[EMAIL]" in redacted
    assert "[CARD]" in redacted
    assert "[PHONE]" in redacted


def test_price_cache_is_bounded() -> None:
    table = PriceTable({"acme/m": ModelPrice(1.0, 1.0)})
    for i in range(1_100):
        table.lookup("acme", f"m-{i}")
    assert len(table._resolved) <= 1_024
    assert table.lookup("acme", "m-5") == ModelPrice(1.0, 1.0)
