from __future__ import annotations

import argparse
import hmac
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from richard_router.config import RouterConfig, load_config, read_config_data, validate_config
from richard_router.service import ClientFactory, RichardRouter, RouterResult, RouterStream


def _check_auth(request: Request, config: RouterConfig) -> None:
    expected = config.inbound_api_key
    if not expected:
        return
    auth = request.headers.get("authorization", "")
    x_api_key = request.headers.get("x-api-key", "")
    expected_bearer = f"Bearer {expected}"
    if hmac.compare_digest(auth, expected_bearer) or hmac.compare_digest(x_api_key, expected):
        return
    raise HTTPException(status_code=401, detail="unauthorized")


def create_app(
    config: RouterConfig | None = None,
    client_factory: ClientFactory | None = None,
) -> FastAPI:
    cfg = config or load_config()
    router = RichardRouter(cfg, client_factory=client_factory)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await router.aclose()

    app = FastAPI(title="richard-router", version="0.1.0", lifespan=lifespan)
    app.state.router_config = cfg
    app.state.richard_router = router

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "virtual_models": list(cfg.virtual_models)}

    @app.get("/v1/models")
    async def models(request: Request) -> dict[str, Any]:
        _check_auth(request, cfg)
        return router.models_payload()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        _check_auth(request, cfg)
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be a JSON object")

        if body.get("stream") is True:
            routed = await router.open_stream(body)
            if isinstance(routed, RouterStream):
                return StreamingResponse(
                    routed.iterator,
                    media_type=routed.media_type,
                    headers=routed.headers,
                )
            return Response(
                content=routed.content,
                status_code=routed.status_code,
                media_type=routed.media_type,
                headers=routed.headers,
            )

        result: RouterResult = await router.chat_completion(body)
        if result.media_type == "application/json":
            try:
                return JSONResponse(
                    content=json.loads(result.content.decode("utf-8")),
                    status_code=result.status_code,
                    headers=result.headers,
                )
            except Exception:
                pass
        return Response(
            content=result.content,
            status_code=result.status_code,
            media_type=result.media_type,
            headers=result.headers,
        )

    return app


class LazyApp:
    def __init__(self) -> None:
        self._app: FastAPI | None = None

    def _get_app(self) -> FastAPI:
        if self._app is None:
            self._app = create_app()
        return self._app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self._get_app()(scope, receive, send)


app = LazyApp()


def _validate_cli(config_path: str) -> int:
    try:
        raw = read_config_data(config_path)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    problems = validate_config(raw)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print("config ok")
    return 0


def cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run richard-router")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4000, type=int)
    parser.add_argument("--config", default=None, help="Path to router YAML config")
    subparsers = parser.add_subparsers(dest="command")
    validate_parser = subparsers.add_parser("validate", help="Validate router YAML config")
    validate_parser.add_argument("--config", required=True, help="Path to router YAML config")
    args = parser.parse_args(argv)
    if args.command == "validate":
        raise SystemExit(_validate_cli(args.config))
    import uvicorn

    uvicorn.run(create_app(load_config(args.config)), host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    cli()
