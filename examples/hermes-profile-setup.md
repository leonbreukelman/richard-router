# Hermes profile setup for richard-router

Use a disposable profile while testing:

```bash
hermes profile create routertest --clone
hermes -p routertest config edit
```

Paste the contents of `examples/hermes-config.yaml` into that profile's
`config.yaml`, or merge the `custom_providers` and `model` sections manually.

Run the router locally:

```bash
cp .env.example .env
cp config/router.example.yaml config/router.yaml
# add NVIDIA_API_KEY and OPENROUTER_API_KEY to .env
uv sync
uv run dotenv -f .env run -- uvicorn richard_router.main:app --host 127.0.0.1 --port 4000
```

Then smoke Hermes:

```bash
hermes -p routertest chat -Q -q 'Reply exactly: ROUTER-OK'
```
