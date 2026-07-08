from __future__ import annotations

import argparse
import hmac
import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from richard_router.config import RouterConfig, load_config
from richard_router.service import RichardRouter, RouterResult, RouterStream


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


def create_app(config: RouterConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    router = RichardRouter(cfg)
    app = FastAPI(title="richard-router", version="0.1.0")
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


app = create_app()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Run richard-router")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4000, type=int)
    parser.add_argument("--config", default=None, help="Path to router YAML config")
    args = parser.parse_args()
    if args.config:
        import os

        os.environ["ROUTER_CONFIG"] = args.config
    import uvicorn

    uvicorn.run("richard_router.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    cli()
