from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel
from database import get_db, row_to_dict
from snmp.process import process_runner
from snmp.mib import mib_manager
from snmp.registry import managed_registry
import re

router = APIRouter()


class SnmpGetRequest(BaseModel):
    device_id: int
    oid: str
    timeout: Optional[int] = None
    retries: Optional[int] = None


class SnmpSetRequest(BaseModel):
    device_id: int
    oid: str
    type_char: str  # i, u, t, a, o, s, x, d, b
    value: str
    verify_get: bool = True
    timeout: Optional[int] = None
    retries: Optional[int] = None


class SnmpGetSetResponse(BaseModel):
    success: bool
    oid: str
    output: str
    parsed_name: Optional[str] = None
    parsed_type: Optional[str] = None
    parsed_value: Optional[str] = None
    is_no_such: bool = False
    verification: Optional[dict] = None
    error: Optional[str] = None


@router.post("/get", response_model=SnmpGetSetResponse)
async def snmp_get_operation(request: SnmpGetRequest, db=Depends(get_db)):
    device = managed_registry.get_device(request.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device = dict(device)
    if request.timeout is not None:
        device["timeout"] = request.timeout
    if request.retries is not None:
        device["retries"] = request.retries

    active_modules = mib_manager.get_loaded_modules()
    success, stdout, stderr = process_runner.run_snmpget(device, request.oid, active_modules)

    if not success:
        db.execute(
            "INSERT INTO query_history (device_id, operation, oid_from, status, result_count, completed_at, error_message) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)",
            (request.device_id, "get", request.oid, "error", 0, stderr or stdout or "SNMP GET failed"),
        )
        return SnmpGetSetResponse(
            success=False,
            oid=request.oid,
            output="",
            error=stderr or stdout or "SNMP GET failed"
        )

    # Detect SNMP exception conditions: "No Such Instance" or "No Such Object"
    is_no_such = "No Such Instance" in stdout or "No Such Object" in stdout
    parsed_name, parsed_type, parsed_value = _parse_snmp_output(stdout)

    db.execute(
        "INSERT INTO query_history (device_id, operation, oid_from, status, result_count, completed_at, error_message) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)",
        (request.device_id, "get", request.oid, "completed" if not is_no_such else "failed", 1 if not is_no_such else 0, stdout if is_no_such else None),
    )

    return SnmpGetSetResponse(
        success=not is_no_such,
        oid=request.oid,
        output=stdout,
        parsed_name=parsed_name,
        parsed_type=parsed_type if not is_no_such else "NO SUCH INSTANCE",
        parsed_value=parsed_value,
        is_no_such=is_no_such,
        error=stdout if is_no_such else None
    )


@router.post("/set", response_model=SnmpGetSetResponse)
async def snmp_set_operation(request: SnmpSetRequest, db=Depends(get_db)):
    device = managed_registry.get_device(request.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device = dict(device)
    if request.timeout is not None:
        device["timeout"] = request.timeout
    if request.retries is not None:
        device["retries"] = request.retries

    # Validate type char against supported Net-SNMP types
    valid_types = {"i", "u", "t", "a", "o", "s", "x", "d", "b"}
    if request.type_char not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid type '{request.type_char}'. Supported: {', '.join(valid_types)}")

    active_modules = mib_manager.get_loaded_modules()
    success, stdout, stderr = process_runner.run_snmpset(
        device,
        request.oid,
        request.type_char,
        request.value,
        active_modules
    )

    if not success:
        db.execute(
            "INSERT INTO query_history (device_id, operation, oid_from, status, result_count, completed_at, error_message) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)",
            (request.device_id, "set", request.oid, "error", 0, stderr or stdout or "SNMP SET failed"),
        )
        return SnmpGetSetResponse(
            success=False,
            oid=request.oid,
            output="",
            error=stderr or stdout or "SNMP SET failed"
        )

    db.execute(
        "INSERT INTO query_history (device_id, operation, oid_from, status, result_count, completed_at, error_message) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)",
        (request.device_id, "set", request.oid, "completed", 1, None),
    )

    parsed_name, parsed_type, parsed_value = _parse_snmp_output(stdout)

    verification = None
    if request.verify_get:
        v_ok, v_out, v_err = process_runner.run_snmpget(device, request.oid, active_modules)
        v_name, v_type, v_val = _parse_snmp_output(v_out) if v_ok else ("", "", "")
        verification = {
            "success": v_ok,
            "output": v_out,
            "verified_value": v_val,
            "error": v_err if not v_ok else None
        }

    return SnmpGetSetResponse(
        success=True,
        oid=request.oid,
        output=stdout,
        parsed_name=parsed_name,
        parsed_type=parsed_type,
        parsed_value=parsed_value,
        verification=verification
    )


def _parse_snmp_output(output: str):
    # e.g. IF-MIB::ifAdminStatus.1 = INTEGER: up(1)
    m = re.match(r"([^=]+)\s*=\s*([^:]+):\s*(.*)", output)
    if m:
        return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    # e.g. IF-MIB::ifAdminStatus.1 = ""
    m2 = re.match(r"([^=]+)\s*=\s*(.*)", output)
    if m2:
        return m2.group(1).strip(), "Value", m2.group(2).strip()
    return output, "", output
