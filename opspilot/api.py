from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from .config import build_agent
from .storage import redact_value
from .tools import LogArgs


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1500, examples=["诊断 orders-api 的错误率和 P95 延迟，给出排查建议"])
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    start_time: str | None = None
    end_time: str | None = None

    @model_validator(mode="after")
    def valid_window(self):
        LogArgs.model_validate({"service": "orders-api", "start_time": self.start_time, "end_time": self.end_time})
        return self

    @field_validator("question")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("question cannot be blank")
        return value


def create_app(agent=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.agent = agent or build_agent()
        yield

    app = FastAPI(title="OpsPilot 故障诊断 Agent", version="0.1.0", lifespan=lifespan,
                  description="本地知识检索与日志分析助手。支持时间范围统计、本地故障实验与可选生成模型。进入 /docs 点击 Try it out 体验。")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_, error):
        # Pydantic's default errors include the raw rejected input, which may be a credential.
        detail = [{key: item[key] for key in ("type", "loc", "msg") if key in item}
                  for item in error.errors()]
        return JSONResponse(status_code=422, content={"detail": redact_value(detail)})

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    @app.get("/health")
    def health():
        current = app.state.agent
        return {"status": "ok", "mode": getattr(current, "configured_mode", "llm" if current.model_factory else "offline"),
                "chunks": len(current.tools.retriever.chunks), "retriever": current.tools.method}

    @app.post("/ask")
    def ask(request: AskRequest):
        try:
            return app.state.agent.ask(request.question, request.session_id or uuid.uuid4().hex,
                                       start_time=request.start_time, end_time=request.end_time)
        except ValueError:
            raise HTTPException(422, "Invalid question or time window; use ISO8601 timestamps with a timezone") from None

    @app.get("/search")
    def search(q: str = Query(min_length=1, max_length=1500), k: int = Query(default=5, ge=1, le=10)):
        return redact_value(app.state.agent.tools.retriever.search(q, k, app.state.agent.tools.method))

    @app.get("/runs/{run_id}")
    def get_run(run_id: str):
        run = app.state.agent.store.get(run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        return run

    @app.get("/documents")
    def documents():
        chunks = app.state.agent.tools.retriever.chunks
        return {"documents": sorted({c.doc_id for c in chunks}), "chunk_count": len(chunks)}

    return app


app = create_app()
