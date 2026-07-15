from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, cast

from azure.core.exceptions import AzureError
from fastapi import FastAPI, Query, Request
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAIError
from redis.exceptions import RedisError

from app.agent import ServiceContainer, build_services
from app.config import Settings, get_settings
from app.models import (
    BoundedId,
    ChatRequest,
    ChatResponse,
    ForgetResponse,
    HealthResponse,
    MemoryItem,
    MemoryListResponse,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)
from app.rate_limit import GlobalApiRateLimitMiddleware
from app.telemetry import configure_telemetry

STATIC_DIR = Path(__file__).parent / "static"
logger = configure_telemetry()


def create_app(
    settings: Settings | None = None,
    services: ServiceContainer | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = services is None
        app.state.services = services or await build_services(resolved_settings)
        logger.info("application_started mode=%s", resolved_settings.app_mode)
        yield
        if owned:
            await cast(ServiceContainer, app.state.services).close()

    application = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        GlobalApiRateLimitMiddleware,
        requests_per_minute=resolved_settings.api_requests_per_minute,
    )
    application.state.settings = resolved_settings
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.exception_handler(AzureError)
    async def azure_error_handler(request: Request, exc: AzureError) -> JSONResponse:
        logger.error(
            "azure_dependency_failure path=%s type=%s",
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "An Azure dependency is temporarily unavailable."},
        )

    @application.exception_handler(RedisError)
    async def redis_error_handler(request: Request, exc: RedisError) -> JSONResponse:
        logger.error(
            "redis_dependency_failure path=%s type=%s",
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Session memory is temporarily unavailable."},
        )

    @application.exception_handler(OpenAIError)
    async def openai_error_handler(request: Request, exc: OpenAIError) -> JSONResponse:
        logger.error(
            "model_dependency_failure path=%s type=%s",
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "The model service is temporarily unavailable."},
        )

    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", mode=resolved_settings.app_mode)

    @application.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        container = _services(request)
        return await container.agent.chat(payload.user_id, payload.session_id, payload.message)

    @application.post("/api/memories/remember", response_model=RememberResponse)
    async def remember(payload: RememberRequest, request: Request) -> RememberResponse:
        result = await _services(request).agent.remember(
            payload.user_id,
            payload.text,
            payload.category,
            payload.source_turn,
        )
        return RememberResponse(
            memory=MemoryItem.from_record(result.memory),
            created=result.created,
        )

    @application.post("/api/memories/recall", response_model=RecallResponse)
    async def recall(payload: RecallRequest, request: Request) -> RecallResponse:
        memories = await _services(request).agent.recall(
            payload.user_id,
            payload.query,
            payload.limit,
        )
        return RecallResponse(memories=memories)

    @application.get("/api/users/{user_id}/memories", response_model=MemoryListResponse)
    async def list_memories(
        request: Request,
        user_id: Annotated[BoundedId, ApiPath()],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> MemoryListResponse:
        records = await _services(request).memory_store.list_memories(user_id, limit)
        return MemoryListResponse(memories=[MemoryItem.from_record(record) for record in records])

    @application.delete(
        "/api/users/{user_id}/memories/{memory_id}",
        response_model=ForgetResponse,
    )
    async def forget(
        request: Request,
        user_id: Annotated[BoundedId, ApiPath()],
        memory_id: Annotated[str, ApiPath(min_length=1, max_length=64)],
    ) -> ForgetResponse:
        forgotten = await _services(request).memory_store.forget(user_id, memory_id)
        return ForgetResponse(forgotten=forgotten)

    return application


def _services(request: Request) -> ServiceContainer:
    return cast(ServiceContainer, request.app.state.services)


app = create_app()
