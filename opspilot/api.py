from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from .models import model_factory_from_env
from .privacy import redact_value
from .triage import analyze_failure


class TriageRequest(BaseModel):
    repo: str = Field(min_length=1, max_length=4096)
    junit: str = Field(min_length=1, max_length=4096)
    base_ref: str | None = Field(default=None, max_length=256)
    notes_dir: str | None = Field(default=None, max_length=4096)
    offline: bool = False

    @field_validator('repo', 'junit', 'base_ref', 'notes_dir')
    @classmethod
    def valid_text(cls, value):
        if value is None:
            return value
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError('Use a non-blank local path or ref without control characters')
        return value


def create_app(model_factory=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.model_factory = model_factory
        app.state.model_config_error = False
        if model_factory is None:
            try:
                app.state.model_factory = model_factory_from_env()
            except ValueError:
                app.state.model_config_error = True
        yield

    app = FastAPI(title='OpsPilot · pytest 失败分析', version='0.2.0', lifespan=lifespan,
                  description='读取本机 JUnit 报告、Git 差异和项目规则，输出带证据的观察与待验证假设。仅供可信本机使用。')

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_, error):
        details = [{key: item[key] for key in ('type', 'loc', 'msg') if key in item} for item in error.errors()]
        return JSONResponse(status_code=422, content={'detail': redact_value(details)})

    @app.get('/', response_class=HTMLResponse, include_in_schema=False)
    def index():
        return (Path(__file__).parent / 'web' / 'index.html').read_text(encoding='utf-8')

    @app.get('/health')
    def health():
        return {'status': 'ok', 'version': '0.2.0', 'mode': os.getenv('OPS_MODE', 'offline')}

    @app.post('/triage')
    def triage(request: TriageRequest):
        if not request.offline and app.state.model_config_error:
            return JSONResponse(status_code=422, content={'detail': 'Invalid model configuration; check OPS_MODE and documented environment variables'})
        factory = None if request.offline else app.state.model_factory
        result = analyze_failure(Path(request.repo), Path(request.junit), request.base_ref,
                                 Path(request.notes_dir) if request.notes_dir else None, factory)
        return JSONResponse(status_code=422 if result['status'] == 'invalid_input' else 200, content=result)

    return app


app = create_app()
