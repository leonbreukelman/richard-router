from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import suppress
from pathlib import Path

from richard_router.config import load_config
from richard_router.service import RichardRouter


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


async def run_once(config_path: str) -> int:
    cfg = load_config(config_path)
    router = RichardRouter(cfg)
    body = {
        "model": "coding",
        "messages": [{"role": "user", "content": "Reply exactly: RICHARD-ROUTER-LIVE-OK"}],
        "temperature": 0,
        "max_tokens": 256,
    }
    result = await router.chat_completion(body)
    payload = None
    with suppress(Exception):
        payload = json.loads(result.content.decode("utf-8"))
    text = ""
    if isinstance(payload, dict):
        try:
            text = payload["choices"][0]["message"].get("content") or ""
        except Exception:
            text = ""
    print(
        json.dumps(
            {
                "status_code": result.status_code,
                "upstream": result.headers.get("x-richard-router-upstream", ""),
                "model": payload.get("model") if isinstance(payload, dict) else None,
                "contains_expected": "RICHARD-ROUTER-LIVE-OK" in text,
                "text_preview": text[:120],
            },
            indent=2,
        )
    )
    return 0 if result.status_code < 400 and "RICHARD-ROUTER-LIVE-OK" in text else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/router.example.yaml")
    parser.add_argument("--env-file", default=str(Path.home() / ".hermes" / ".env"))
    args = parser.parse_args()
    load_env_file(Path(args.env_file))
    raise SystemExit(asyncio.run(run_once(args.config)))


if __name__ == "__main__":
    main()
