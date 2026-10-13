from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel
import uuid
from database import get_db, row_to_dict
from snmp.client import DeviceConfig
from snmp.walk import walk_engine, WalkSession
from snmp.mib import mib_manager
from snmp.process import process_runner
from snmp.registry import managed_registry
from export.formatter import format_walk_export
from datetime import datetime
import os

walk_engine.mib_loader = mib_manager.get_loader()

router = APIRouter()


class WalkRequest(BaseModel):
    device_id: int
    oid_from: str
    oid_to: Optional[str] = None
    use_bulk: bool = True
    timeout: Optional[int] = None
    retries: Optional[int] = None


class WalkStartResponse(BaseModel):
    session_id: str
    status: str


class WalkStatusResponse(BaseModel):
    session_id: str
    status: str
    result_count: int
    error: Optional[str] = None


class WalkResultRow(BaseModel):
    oid: str
    name: str
    type: str
    value: str
    index: str = ""
    status: str = "ok"
    error_msg: Optional[str] = None
    seq: int = 0
    display_value: Optional[str] = None
    display_type: Optional[str] = None


class WalkResultsResponse(BaseModel):
    session_id: str
    status: str
    results: List[WalkResultRow]
    total: int
    success_count: int = 0
    failed_count: int = 0


class ExportRequest(BaseModel):
    filename: Optional[str] = None


class ExportResponse(BaseModel):
    success: bool
    path: Optional[str] = None
    content: Optional[str] = None
    message: str


@router.post("/start", response_model=WalkStartResponse)
async def start_walk(request: WalkRequest, db=Depends(get_db)):
    device = managed_registry.get_device(request.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device = dict(device)
    if request.timeout is not None:
        device["timeout"] = request.timeout
    if request.retries is not None:
        device["retries"] = request.retries

    # Validate To OID if provided
    if request.oid_to and request.oid_to.strip():
        req_to = request.oid_to.strip()
        req_from = request.oid_from.strip()
        try:
            parts_from = [int(x) for x in req_from.split(".") if x]
            parts_to = [int(x) for x in req_to.split(".") if x]
            if parts_from and parts_to:
                cmp_val = 0
                for a, b in zip(parts_from, parts_to):
                    if a < b:
                        cmp_val = -1
                        break
                    elif a > b:
                        cmp_val = 1
                        break
                if cmp_val == 0:
                    if len(parts_from) < len(parts_to):
                        cmp_val = -1
                    elif len(parts_from) > len(parts_to):
                        cmp_val = 1
                if cmp_val >= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"To OID ({req_to}) must be greater than Target/From OID ({req_from}). Leave 'To OID' blank to walk the full subtree."
                    )
        except ValueError:
            pass

    config = DeviceConfig(
        ip=device["ip_address"],
        port=device["port"],
        community=device["read_community"],
        version=device["version"],
        retries=device["retries"],
        timeout=device["timeout"],
        username=device["username"],
        auth_protocol=device["auth_protocol"],
        auth_password=device["auth_password"],
        privacy_protocol=device["privacy_protocol"],
        privacy_password=device["privacy_password"],
    )

    session_id = str(uuid.uuid4())[:8]

    async def progress_callback(batch):
        pass

    session = await walk_engine.start_walk(
        session_id=session_id,
        device_config=config,
        oid_from=request.oid_from,
        oid_to=request.oid_to,
        use_bulk=request.use_bulk,
        progress_callback=progress_callback,
    )
    session.device_id = request.device_id

    cur = db.execute(
        "INSERT INTO query_history (device_id, operation, oid_from, oid_to, status) VALUES (?, ?, ?, ?, ?)",
        (request.device_id, "walk", request.oid_from, request.oid_to, "running"),
    )
    session.history_id = cur.lastrowid

    return WalkStartResponse(session_id=session_id, status="running")


@router.post("/stop/{session_id}")
async def stop_walk(session_id: str, db=Depends(get_db)):
    success = walk_engine.stop_walk(session_id)
    session = walk_engine.get_session(session_id)
    if session and hasattr(session, "history_id") and session.history_id:
        db.execute(
            "UPDATE query_history SET status = 'stopped', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (session.history_id,)
        )
    return {"success": success}


@router.post("/stop-all")
async def stop_all_operations(db=Depends(get_db)):
    stopped_walks = walk_engine.stop_all()
    process_runner.kill_all_snmp_tasks()
    db.execute("UPDATE query_history SET status = 'stopped', completed_at = CURRENT_TIMESTAMP WHERE status = 'running'")
    return {"success": True, "stopped_walks": stopped_walks}


@router.get("/status/{session_id}", response_model=WalkStatusResponse)
async def walk_status(session_id: str):
    session = walk_engine.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return WalkStatusResponse(
        session_id=session_id,
        status=session.status,
        result_count=len(session.results),
        error=session.error,
    )


@router.get("/results/{session_id}", response_model=WalkResultsResponse)
async def walk_results(session_id: str, limit: int = 50000, offset: int = 0):
    session = walk_engine.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    sorted_results = sorted(session.results, key=lambda x: getattr(x, "seq", 0))
    results = sorted_results[offset:offset + limit]
    success_count = sum(1 for r in session.results if getattr(r, "status", "ok") == "ok")
    failed_count = sum(1 for r in session.results if getattr(r, "status", "ok") != "ok")
    return WalkResultsResponse(
        session_id=session_id,
        status=session.status,
        results=[WalkResultRow(**r.__dict__) for r in results],
        total=len(session.results),
        success_count=success_count,
        failed_count=failed_count,
    )


@router.post("/export/{session_id}", response_model=ExportResponse)
async def export_walk(session_id: str, request: ExportRequest, db=Depends(get_db)):
    session = walk_engine.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    device = managed_registry.get_device(session.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device = dict(device)

    export_content = format_walk_export(
        device=device,
        session=session,
        oid_from=session.oid_from,
        oid_to=session.oid_to,
    )

    export_dir = os.path.expanduser("~/.snmp-manager/exports")
    os.makedirs(export_dir, exist_ok=True)

    filename = request.filename or f"walk_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    filepath = os.path.join(export_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(export_content)

    if hasattr(session, "history_id") and session.history_id:
        db.execute(
            "UPDATE query_history SET status = ?, result_count = ?, export_path = ?, completed_at = ?, error_message = ? WHERE id = ?",
            (session.status, len(session.results), filepath, session.completed_at, session.error, session.history_id),
        )

    return ExportResponse(success=True, path=filepath, content=export_content, message="Export successful")


@router.get("/history")
async def walk_history(db=Depends(get_db)):
    rows = db.execute(
        "SELECT * FROM query_history ORDER BY started_at DESC LIMIT 100"
    ).fetchall()
    results = []
    for r in rows:
        item = row_to_dict(r)
        dev = managed_registry.get_device(item.get("device_id", 0))
        item["device_name"] = dev["name"] if dev else f"Device #{item.get('device_id')}"
        item["ip_address"] = dev["ip_address"] if dev else "Unknown"
        results.append(item)
    return results


@router.delete("/history")
async def clear_history(db=Depends(get_db)):
    db.execute("DELETE FROM query_history")
    return {"success": True, "message": "History cleared"}