import os
import shutil
import re
import sys
import json
import hashlib
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field

WORKSPACE_DIR = os.path.expanduser("~/.snmp-manager/workspace/mibs")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

def find_bundled_mibs_dir():
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        meipass = getattr(sys, "_MEIPASS", "")
        # Retain root folder (mibs/ only)
        candidates.append(os.path.join(exe_dir, "mibs"))
        if meipass:
            candidates.append(os.path.join(meipass, "mibs"))
    else:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        candidates.append(os.path.join(root_dir, "mibs"))
        candidates.append(os.path.join(root_dir, "share", "snmp", "mibs"))
    candidates.append(r"C:\net-snmp\mibs")
    candidates.append(r"C:\net-snmp\share\snmp\mibs")
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return candidates[0]

def find_net_snmp_bin_dir():
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        meipass = getattr(sys, "_MEIPASS", "")
        candidates.append(os.path.join(exe_dir, "bin"))
        if meipass:
            candidates.append(os.path.join(meipass, "bin"))
    else:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        candidates.append(os.path.join(root_dir, "bin"))
    candidates.append(r"C:\net-snmp\bin")
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return candidates[0]

BUNDLED_MIBS_DIR = find_bundled_mibs_dir()
NET_SNMP_BIN_DIR = find_net_snmp_bin_dir()


@dataclass
class MibFileInfo:
    filename: str
    filepath: str
    module_name: str
    imports: List[str] = field(default_factory=list)
    is_valid_mib: bool = False


class MibWorkspaceManager:
    """Manages an isolated application workspace for MIB files."""

    def __init__(self, workspace_dir: str = WORKSPACE_DIR):
        self.workspace_dir = workspace_dir
        os.makedirs(self.workspace_dir, exist_ok=True)

    def parse_mib_header(self, filepath: str) -> MibFileInfo:
        """Parse ASN.1 header from file to extract module name and IMPORTS."""
        filename = os.path.basename(filepath)
        if not os.path.isfile(filepath):
            return MibFileInfo(filename=filename, filepath=filepath, module_name="", is_valid_mib=False)

        try:
            if os.path.getsize(filepath) > 10 * 1024 * 1024:
                return MibFileInfo(filename=filename, filepath=filepath, module_name="", is_valid_mib=False)
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            return MibFileInfo(filename=filename, filepath=filepath, module_name="", is_valid_mib=False)

        # Look for MODULE-NAME DEFINITIONS ::= BEGIN
        mod_match = re.search(r"([A-Za-z0-9_-]+)\s+DEFINITIONS\s*::=\s*BEGIN", content)
        if not mod_match:
            return MibFileInfo(filename=filename, filepath=filepath, module_name="", is_valid_mib=False)

        module_name = mod_match.group(1).strip()

        # Parse IMPORTS ... FROM ModuleName;
        imports = []
        imports_match = re.search(r"IMPORTS\s+(.*?);", content, re.DOTALL)
        if imports_match:
            imp_block = imports_match.group(1)
            # Find all FROM <Module>
            from_matches = re.findall(r"FROM\s+([A-Za-z0-9_-]+)", imp_block)
            imports = list(dict.fromkeys(from_matches))  # preserve order, unique

        return MibFileInfo(
            filename=filename,
            filepath=filepath,
            module_name=module_name,
            imports=imports,
            is_valid_mib=True
        )

    def stage_file_to_workspace(self, src_path: str) -> Tuple[str, MibFileInfo]:
        """
        Copy the MIB file to workspace without modifying the original.
        Returns (destination_path, MibFileInfo).
        """
        if not os.path.isfile(src_path):
            raise FileNotFoundError(f"Source MIB file not found: {src_path}")

        info = self.parse_mib_header(src_path)
        if not info.is_valid_mib:
            raise ValueError(f"File is not a valid ASN.1 MIB: {src_path}")

        # Destination filename: preserve original filename, or use module_name.txt if ambiguous
        dest_filename = os.path.basename(src_path)
        dest_path = os.path.join(self.workspace_dir, dest_filename)

        # Non-destructive copy of original file
        if os.path.abspath(src_path) != os.path.abspath(dest_path):
            shutil.copy2(src_path, dest_path)

        # Also ensure file is aliased under its canonical module_name so PySMI and Net-SNMP can find it
        if info.module_name:
            canonical_path = os.path.join(self.workspace_dir, f"{info.module_name}.mib")
            if os.path.abspath(dest_path) != os.path.abspath(canonical_path):
                shutil.copy2(dest_path, canonical_path)

        info.filepath = dest_path
        info.filename = dest_filename
        return dest_path, info

    def list_workspace_mibs(self) -> List[MibFileInfo]:
        """List all valid MIB files in the managed workspace (deduplicated by module name)."""
        results = []
        seen_modules = set()
        if not os.path.isdir(self.workspace_dir):
            return results

        for fname in sorted(os.listdir(self.workspace_dir)):
            fpath = os.path.join(self.workspace_dir, fname)
            if os.path.isfile(fpath):
                info = self.parse_mib_header(fpath)
                if info.is_valid_mib and info.module_name:
                    if info.module_name not in seen_modules:
                        seen_modules.add(info.module_name)
                        results.append(info)
        return results

    def remove_from_workspace(self, module_name_or_filename: str) -> bool:
        """Remove all staged files associated with a module or filename from workspace."""
        removed = False
        target = module_name_or_filename.strip().lower()
        if not os.path.isdir(self.workspace_dir):
            return False

        for fname in list(os.listdir(self.workspace_dir)):
            fpath = os.path.join(self.workspace_dir, fname)
            if not os.path.isfile(fpath):
                continue
            base = fname.rsplit(".", 1)[0].lower()
            should_remove = False

            if fname.lower() == target or base == target:
                should_remove = True
            else:
                info = self.parse_mib_header(fpath)
                if info.is_valid_mib and info.module_name:
                    if info.module_name.lower() == target or info.filename.lower() == target:
                        should_remove = True

            if should_remove:
                try:
                    os.remove(fpath)
                    removed = True
                except Exception as e:
                    print(f"Warning: Failed to remove staged workspace file {fpath}: {e}")
        return removed

    def clear_workspace(self):
        """Remove all files in the managed workspace."""
        if os.path.isdir(self.workspace_dir):
            for fname in os.listdir(self.workspace_dir):
                fpath = os.path.join(self.workspace_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass


workspace_manager = MibWorkspaceManager()
