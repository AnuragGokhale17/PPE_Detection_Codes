import logging

from fastapi import FastAPI
from sqlalchemy import text

from app.db.session import engine
from app.routers import auth, config, dashboard, events, samples, training, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="PPE Safety Platform API",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

for module in (auth, users, dashboard, events, samples, config, training):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health", tags=["health"])
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    return {"status": "ok", "database": database}
