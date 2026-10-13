from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from typing import List, Optional, Dict
from pydantic import BaseModel
import os
import shutil
from snmp.mib import mib_manager, MibModuleInfo, MibObjectInfo
from snmp.workspace import workspace_manager

router = APIRouter()


class MibModuleResponse(BaseModel):
    name: str
    path: str
    loaded: bool
    status: str = ""
    object_count: int = 0
    dependencies: List[str] = []
    category: str = "packaged"
    is_managed: bool = False
    original_path: str = ""


class LoadFileRequest(BaseModel):
    filepath: str


class LoadModuleRequest(BaseModel):
    module_name: str
    source_dir: Optional[str] = None


class UnloadModuleRequest(BaseModel):
    module_name: str


class ReloadModuleRequest(BaseModel):
    module_name: str


class RemoveModuleRequest(BaseModel):
    module_name: str


class MibObjectResponse(BaseModel):
    name: str
    oid: str
    module: str
    syntax: str = ""
    max_access: str = "read-only"
    status: str = "current"
    description: str = ""
    enums: Dict[str, int] = {}
    is_table: bool = False
    is_column: bool = False


@router.get("", response_model=List[MibModuleResponse])
async def list_mibs(dir: Optional[str] = Query(None)):
    modules = mib_manager.scan_mibs(dir)
    return [MibModuleResponse(**m.__dict__) for m in modules]


@router.get("/loaded", response_model=List[str])
async def list_loaded_mibs():
    return mib_manager.get_loaded_modules()


@router.post("/load-file")
async def load_mib_file(request: LoadFileRequest):
    res = mib_manager.load_file(request.filepath)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to load MIB file"))
    return res


@router.post("/upload")
async def upload_mib_file(file: UploadFile = File(...)):
    """Upload an arbitrary MIB file directly from browser file picker."""
    dest_path = os.path.join(workspace_manager.workspace_dir, file.filename)
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    res = mib_manager.load_file(dest_path)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to compile uploaded MIB"))
    return res


@router.post("/load")
async def load_module(request: LoadModuleRequest):
    res = mib_manager.load_module(request.module_name, request.source_dir)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to load MIB module"))
    return res


@router.post("/unload")
async def unload_module(request: UnloadModuleRequest):
    res = mib_manager.unload_module(request.module_name)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.post("/reload")
async def reload_module(request: ReloadModuleRequest):
    res = mib_manager.reload_module(request.module_name)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.post("/remove")
async def remove_module(request: RemoveModuleRequest):
    res = mib_manager.remove_module(request.module_name)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.post("/unload-all")
async def unload_all_modules():
    return mib_manager.unload_all()


@router.get("/objects", response_model=List[MibObjectResponse])
async def get_objects(q: Optional[str] = Query(""), module: Optional[str] = Query("")):
    objs = mib_manager.search_objects(q or "", module or "")
    return [MibObjectResponse(**o.__dict__) for o in objs]


@router.get("/tree")
async def get_mib_tree():
    """Returns the hierarchical MIB tree structure."""
    return mib_manager.get_tree()


@router.get("/resolve/{oid:path}")
async def resolve_oid(oid: str):
    name = mib_manager.resolve_oid(oid)
    return {"oid": oid, "name": name}