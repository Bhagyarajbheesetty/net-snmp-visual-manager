from dataclasses import dataclass, asdict
from typing import Optional
from datetime import datetime


@dataclass
class Device:
    id: Optional[int] = None
    name: str = ""
    ip_address: str = ""
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
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_row(cls, row):
        if row is None:
            return None
        d = dict(row) if hasattr(row, "keys") else row
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class QueryHistory:
    id: Optional[int] = None
    device_id: int = 0
    operation: str = ""
    oid_from: str = ""
    oid_to: Optional[str] = None
    status: str = ""
    result_count: int = 0
    export_path: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class MibModule:
    id: Optional[int] = None
    name: str = ""
    path: str = ""
    loaded: bool = False
    loaded_at: Optional[str] = None
    object_count: int = 0