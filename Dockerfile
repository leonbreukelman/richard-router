FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY richard_router ./richard_router
RUN pip install --no-cache-dir .
COPY config/router.example.yaml ./config/router.example.yaml
EXPOSE 4000
CMD ["uvicorn", "richard_router.main:app", "--host", "0.0.0.0", "--port", "4000"]
