import ipaddress
from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from snmp.registry import managed_registry
from snmp.client import DeviceConfig, SNMPClient

router = APIRouter()


def normalize_ip_address(ip_str: str) -> str:
    """
    Validates and normalizes an IPv4 or IPv6 address.
    Strips leading and trailing whitespace and formats into canonical string representation.
    Raises ValueError with descriptive message if the address is invalid.
    """
    return managed_registry.normalize_ip(ip_str)


def check_ip_exists(normalized_ip: str, exclude_device_id: Optional[int] = None) -> bool:
    """
    Checks whether a normalized IP address is already registered to another device.
    """
    return managed_registry.check_ip_exists(normalized_ip, exclude_device_id)


class DeviceCreate(BaseModel):
    name: str
    ip_address: str
    port: int = 161
    version: str = "v2c"
    read_community: str = "public"
    write_community: str = "private"
    retries: int = 2
    timeout: int = 2
    username: Optional[str] = None
    auth_protocol: Optional[str] = None
    auth_password: Optional[str] = None
    privacy_protocol: Optional[str] = None
    privacy_password: Optional[str] = None


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = None
    version: Optional[str] = None
    read_community: Optional[str] = None
    write_community: Optional[str] = None
    retries: Optional[int] = None
    timeout: Optional[int] = None
    username: Optional[str] = None
    auth_protocol: Optional[str] = None
    auth_password: Optional[str] = None
    privacy_protocol: Optional[str] = None
    privacy_password: Optional[str] = None


class DeviceTestResponse(BaseModel):
    success: bool
    message: str
    sys_descr: Optional[str] = None


@router.get("")
async def list_devices():
    return managed_registry.list_devices()


@router.post("")
async def create_device(device: DeviceCreate):
    try:
        normalized_ip = normalize_ip_address(device.ip_address)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    data = device.model_dump()
    data["ip_address"] = normalized_ip
    try:
        new_record = managed_registry.add_device(data)
        return new_record
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{device_id}")
async def get_device(device_id: int):
    row = managed_registry.get_device(device_id)
    if not row:
        raise HTTPException(status_code=404, detail="Device not found")
    return row


@router.put("/{device_id}")
async def update_device(device_id: int, device: DeviceUpdate):
    data = {k: v for k, v in device.model_dump(exclude_unset=True).items() if v is not None}
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        row = managed_registry.update_device(device_id, data)
        if not row:
            raise HTTPException(status_code=404, detail="Device not found")
        return row
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{device_id}")
async def delete_device(device_id: int):
    success = managed_registry.delete_device(device_id)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"success": True}


@router.post("/{device_id}/test", response_model=DeviceTestResponse)
async def test_device(device_id: int):
    row = managed_registry.get_device(device_id)
    if not row:
        raise HTTPException(status_code=404, detail="Device not found")

    config = DeviceConfig(
        ip=row["ip_address"],
        port=row["port"],
        community=row["read_community"],
        version=row["version"],
        retries=row["retries"],
        timeout=row["timeout"],
        username=row.get("username"),
        auth_protocol=row.get("auth_protocol"),
        auth_password=row.get("auth_password"),
        privacy_protocol=row.get("privacy_protocol"),
        privacy_password=row.get("privacy_password"),
    )

    try:
        client = SNMPClient(config)
        result = await client.get(["1.3.6.1.2.1.1.1.0"])
        if result:
            return DeviceTestResponse(success=True, message="Connection successful", sys_descr=result[0].value)
        return DeviceTestResponse(success=False, message="No response from device")
    except Exception as e:
        return DeviceTestResponse(success=False, message=str(e))