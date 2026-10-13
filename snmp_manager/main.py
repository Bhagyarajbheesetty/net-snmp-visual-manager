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


app = FastAPI(title="SNMP Visual Manager", version="1.0.0", lifespan=lifespan)

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
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/about")
async def about():
    return {
        "app_name": "SNMP Visual Manager",
        "version": "1.0.0",
        "license": "MIT",
        "net_snmp_version": "5.9.5.2",
        "net_snmp_web": "http://www.net-snmp.org/",
        "net_snmp_email": "net-snmp-coders@lists.sourceforge.net",
        "author": "Bhagyaraj Bheesetty",
        "credits": "Built with Net-SNMP 5.9.5.2 (http://www.net-snmp.org/). All rights and copyrights reserved by original Net-SNMP authors and contributors. Free open-source tool for SNMP management."
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)