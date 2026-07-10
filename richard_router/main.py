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
from richard_router.metrics import MetricsCollector
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
    obs = cfg.observability
    metrics = MetricsCollector(
        window_size=obs.metrics_window,
        down_threshold=obs.down_threshold,
        degraded_threshold=obs.degraded_threshold,
        degraded_error_pct=obs.degraded_error_pct,
    )
    router = RichardRouter(cfg, client_factory=client_factory, metrics=metrics)

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

    @app.get("/v1/pool")
    async def pool(request: Request) -> dict[str, Any]:
        _check_auth(request, cfg)
        return router.metrics.snapshot().to_dict() if router.metrics else {"virtual_models": {}}

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


def _status_cli(args: argparse.Namespace) -> int:
    import urllib.request

    base_url = args.url.rstrip("/")
    headers = {}
    api_key_env = args.api_key_env
    if api_key_env:
        import os

        key = os.environ.get(api_key_env, "")
        if key:
            headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(f"{base_url}/v1/pool", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Connection failed: {exc.reason}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON response: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    vms = data.get("virtual_models", {})
    if not vms:
        print("No pool data available (router may not have served any requests yet).")
        return 0

    if args.vm:
        vm_filter = args.vm
        if vm_filter not in vms:
            print(f"Virtual model '{vm_filter}' not found. Available: {list(vms)}", file=sys.stderr)
            return 1
        vms = {vm_filter: vms[vm_filter]}

    # Terminal table output
    header = (
        f"{'Virtual Model':<20} {'Pool Member':<30} {'Status':<11} {'Requests':<10} "
        f"{'Success':<10} {'Errors':<8} {'Err Rate':<9} Last Active"
    )
    sep = "─" * len(header)
    print(header)
    print(sep)
    sorted_vm_names = sorted(vms)
    for vm_index, vm_name in enumerate(sorted_vm_names):
        if vm_index > 0:
            print()
        upstreams = sorted(vms[vm_name], key=lambda u: u["name"])
        for row_idx, up in enumerate(upstreams):
            vm_col = vm_name if row_idx == 0 else ""
            last_active = up.get("last_ok") or up.get("last_error") or "—"
            if last_active and last_active != "—":
                # Trim ISO timestamp to readable form
                last_active = last_active.replace("T", " ").replace("Z", "")
            print(
                f"{vm_col:<20} {up['name']:<30} {up['status']:<11} "
                f"{up['total_requests']:<10} {up['success_count']:<10} "
                f"{up['error_count']:<8} {up['error_rate_pct']:<9} {last_active}"
            )

    return 0


def cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run richard-router")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4000, type=int)
    parser.add_argument("--config", default=None, help="Path to router YAML config")
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser("validate", help="Validate router YAML config")
    validate_parser.add_argument("--config", required=True, help="Path to router YAML config")

    status_parser = subparsers.add_parser(
        "status", help="Show pool member metrics and health status"
    )
    status_parser.add_argument("--url", default="http://127.0.0.1:4000", help="Router base URL")
    status_parser.add_argument("--vm", default=None, help="Filter to a single virtual model")
    status_parser.add_argument("--json", action="store_true", help="Output raw JSON")
    status_parser.add_argument(
        "--api-key-env",
        default="RICHARD_ROUTER_API_KEY",
        help="Env var holding the router API key (for auth)",
    )
    status_parser.add_argument("--timeout", default=10, type=int, help="HTTP request timeout (s)")

    args = parser.parse_args(argv)
    if args.command == "validate":
        raise SystemExit(_validate_cli(args.config))
    if args.command == "status":
        raise SystemExit(_status_cli(args))
    import uvicorn

    uvicorn.run(create_app(load_config(args.config)), host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    cli()
