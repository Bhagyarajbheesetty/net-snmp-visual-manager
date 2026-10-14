from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional, Dict, Any
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
    resolved_oid = request.oid

    # Intelligent Table Column & Multi-Index Resolution:
    # If standard exact GET failed because this OID is a table column or un-instantiated object (e.g. linkProfileDDRSMinDataRate),
    # probe with snmpgetnext to retrieve the first actual row instance of this column!
    if is_no_such and not request.oid.endswith(".0"):
        next_ok, next_out, next_err = process_runner.run_snmpgetnext(device, request.oid, active_modules)
        if next_ok and next_out and "No Such" not in next_out:
            n_name, n_type, n_val = _parse_snmp_output(next_out)
            clean_req = request.oid.split("::")[-1].strip(".")
            oid_info = process_runner.translate_oid_details(request.oid, modules=active_modules) or {}
            target_name = oid_info.get("name", "")

            is_match = (
                clean_req in n_name
                or (target_name and target_name in n_name)
                or next_out.startswith(clean_req)
            )
            if is_match:
                is_no_such = False
                stdout = next_out
                parsed_name = n_name
                parsed_type = n_type
                parsed_value = n_val
                resolved_oid = n_name.split("=")[0].strip() if "=" in n_name else n_name

    db.execute(
        "INSERT INTO query_history (device_id, operation, oid_from, status, result_count, completed_at, error_message) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)",
        (request.device_id, "get", request.oid, "completed" if not is_no_such else "failed", 1 if not is_no_such else 0, stdout if is_no_such else None),
    )

    return SnmpGetSetResponse(
        success=not is_no_such,
        oid=resolved_oid,
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


class OidDetailsResponse(BaseModel):
    oid: str
    symbol: str = ""
    name: str = ""
    syntax: str = ""
    type_char: str = "i"
    max_access: str = ""
    status: str = ""
    description: str = ""
    defval: str = ""
    enums: Dict[str, int] = {}
    has_enums: bool = False
    description_details: Optional[Dict[str, Any]] = None


@router.get("/oid-details", response_model=OidDetailsResponse)
async def get_oid_details(oid: str = Query(...)):
    if not oid or not oid.strip():
        raise HTTPException(status_code=400, detail="OID cannot be empty")

    clean_oid = oid.strip()
    active_modules = mib_manager.get_loaded_modules()
    details = process_runner.translate_oid_details(clean_oid, modules=active_modules)

    if details:
        return OidDetailsResponse(
            oid=clean_oid,
            symbol=details.get("symbol", ""),
            name=details.get("name", "") or clean_oid,
            syntax=details.get("syntax", ""),
            type_char=details.get("type_char", "i"),
            max_access=details.get("max_access", ""),
            status=details.get("status", ""),
            description=details.get("description", ""),
            defval=details.get("defval", ""),
            enums=details.get("enums", {}),
            has_enums=details.get("has_enums", False),
            description_details=details.get("description_details"),
        )

    # Fallback to mib_manager objects cache
    matched_obj = None
    target_clean = clean_oid.lower()
    base_target = target_clean.rsplit(".", 1)[0] if "." in target_clean else target_clean

    for mod in active_modules:
        objs = mib_manager._objects_cache.get(mod, [])
        for obj in objs:
            o_oid = obj.oid.lower()
            o_name = obj.name.lower()
            if target_clean in (o_oid, o_name) or base_target in (o_oid, o_name):
                matched_obj = obj
                break
        if matched_obj:
            break

    if matched_obj:
        enums = getattr(matched_obj, "enums", {})
        raw_desc = getattr(matched_obj, "description", "")
        desc_details = process_runner.parse_description_sections(raw_desc) if raw_desc else None
        if not enums and desc_details and desc_details.get("set_options"):
            enums = desc_details["set_options"]
        has_enums = bool(enums)
        syn = getattr(matched_obj, "syntax", "")
        type_char = "i" if has_enums or "INTEGER" in syn.upper() else "s"
        return OidDetailsResponse(
            oid=clean_oid,
            symbol=f"{matched_obj.module}::{matched_obj.name}",
            name=matched_obj.name,
            syntax=syn,
            type_char=type_char,
            max_access=getattr(matched_obj, "max_access", ""),
            status=getattr(matched_obj, "status", ""),
            description=desc_details.get("formatted_text") if desc_details else raw_desc,
            defval="",
            enums=enums,
            has_enums=has_enums,
            description_details=desc_details,
        )

    return OidDetailsResponse(
        oid=clean_oid,
        symbol=clean_oid,
        name=clean_oid.split(".")[-1] if "." in clean_oid else clean_oid,
        syntax="",
        type_char="i",
        max_access="",
        status="",
        description="",
        defval="",
        enums={},
        has_enums=False,
        description_details=None,
    )
