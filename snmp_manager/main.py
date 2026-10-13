from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import sys

from database import init_db
from api import devices, mibs, walk, operations


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="SNMP Visual Manager", lifespan=lifespan)

app.include_router(devices.router, prefix="/api/devices", tags=["devices"])
app.include_router(mibs.router, prefix="/api/mibs", tags=["mibs"])
app.include_router(walk.router, prefix="/api/walk", tags=["walk"])
app.include_router(operations.router, prefix="/api/operations", tags=["operations"])

def get_static_dir():
    candidates = []
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        candidates.append(os.path.join(base, "snmp_manager", "static"))
        candidates.append(os.path.join(base, "static"))
    candidates.append(os.path.join(os.path.dirname(__file__), "static"))
    candidates.append(os.path.join(os.path.dirname(__file__), "snmp_manager", "static"))
    for c in candidates:
        if os.path.isdir(c):
            return c
    return os.path.join(os.path.dirname(__file__), "static")

static_dir = get_static_dir()
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)