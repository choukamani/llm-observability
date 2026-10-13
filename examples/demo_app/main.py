"""Demo API: a fake LLM chat endpoint instrumented with llmobs.

Run with `docker compose up` (exports to the bundled collector) or locally
with `uvicorn demo_app.main:app` (no exporter unless OTEL_EXPORTER_OTLP_ENDPOINT is set).
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

import llmobs
from llmobs.clients import ChatClient, FakeChatClient, InstrumentedChatClient
from llmobs.sinks import BudgetAlertSink, BudgetExceeded, LoggingSink

logger = logging.getLogger("demo_app")

MODELS = ("fake-small", "fake-large")


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8_000)
    model: str = "fake-small"
    feature: str = "chat"


class ChatResponse(BaseModel):
    text: str
    model: str


def alert(event: BudgetExceeded) -> None:
    logger.warning(
        "budget exceeded for %s: %.4f USD > %.2f USD", event.key, event.spent_usd, event.budget_usd
    )


def build_client(*, fail_ratio: float, seed: int | None) -> ChatClient:
    instrumentor = llmobs.Instrumentor.create(
        subscribers=[
            LoggingSink(),
            BudgetAlertSink({"acme": 0.50, "globex": 0.50, "initech": 0.50}, alert),
        ]
    )
    fake = FakeChatClient(
        seed=seed,
        rate_limit_ratio=fail_ratio * 0.6,
        unavailable_ratio=fail_ratio * 0.25,
        timeout_ratio=fail_ratio * 0.15,
    )
    return InstrumentedChatClient(fake, instrumentor)


def create_app(*, fail_ratio: float = 0.05, seed: int | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        providers = None
        if endpoint:  # pragma: no cover - needs a running collector
            from llmobs.otel import configure

            providers = configure(os.getenv("OTEL_SERVICE_NAME", "llmobs-demo"), endpoint)
        app.state.client = build_client(fail_ratio=fail_ratio, seed=seed)
        yield
        if providers is not None:  # pragma: no cover
            providers.shutdown()

    app = FastAPI(title="llmobs demo", version=llmobs.__version__, lifespan=lifespan)

    @app.middleware("http")
    async def tenant_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Every LLM call made while serving this request is labelled with the tenant.
        with llmobs.attributes(tenant=request.headers.get("x-tenant", "anonymous")):
            return await call_next(request)

    @app.post("/v1/chat")
    async def chat(
        body: ChatRequest, request: Request, x_tenant: Annotated[str, Header()] = "anonymous"
    ) -> ChatResponse:
        if body.model not in MODELS:
            raise HTTPException(422, f"unknown model, expected one of {MODELS}")
        client: ChatClient = request.app.state.client
        with llmobs.attributes(feature=body.feature):
            try:
                completion = await client.complete(body.prompt, model=body.model)
            except TimeoutError as exc:
                raise HTTPException(504, "LLM timeout") from exc
            except Exception as exc:
                status = getattr(exc, "status_code", 502)
                raise HTTPException(status, f"LLM error for tenant {x_tenant}") from exc
        return ChatResponse(text=completion.text, model=completion.model)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app(fail_ratio=float(os.getenv("DEMO_FAIL_RATIO", "0.05")))
