import os
import re
import shutil
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
from snmp.client import MIBLoader
from snmp.workspace import workspace_manager, MibFileInfo, BUNDLED_MIBS_DIR
from snmp.resolver import dependency_resolver
from snmp.process import process_runner
from snmp.registry import managed_registry, is_in_directory


@dataclass
class MibModuleInfo:
    name: str
    path: str
    loaded: bool
    status: str = ""
    object_count: int = 0
    dependencies: List[str] = field(default_factory=list)
    category: str = "packaged"  # "packaged", "staged", "custom"
    is_managed: bool = False
    original_path: str = ""


@dataclass
class MibObjectInfo:
    name: str
    oid: str
    module: str
    syntax: str = ""
    max_access: str = "read-only"
    status: str = "current"
    description: str = ""
    enums: Dict[str, int] = field(default_factory=dict)
    is_table: bool = False
    is_column: bool = False


STANDARD_BUNDLED_MIBS = {
    "AGENTX-MIB", "BRIDGE-MIB", "DISMAN-EVENT-MIB", "DISMAN-SCHEDULE-MIB", "DISMAN-SCRIPT-MIB",
    "EtherLike-MIB", "HCNUM-TC", "HOST-RESOURCES-MIB", "HOST-RESOURCES-TYPES",
    "IANA-ADDRESS-FAMILY-NUMBERS-MIB", "IANA-LANGUAGE-MIB", "IANA-RTPROTO-MIB", "IANAifType-MIB",
    "IF-INVERTED-STACK-MIB", "IF-MIB", "INET-ADDRESS-MIB", "IP-FORWARD-MIB", "IP-MIB",
    "IPV6-FLOW-LABEL-MIB", "IPV6-ICMP-MIB", "IPV6-MIB", "IPV6-TC", "IPV6-TCP-MIB", "IPV6-UDP-MIB",
    "NET-SNMP-AGENT-MIB", "NET-SNMP-EXAMPLES-MIB", "NET-SNMP-EXTEND-MIB", "NET-SNMP-MIB",
    "NET-SNMP-PASS-MIB", "NET-SNMP-TC", "NET-SNMP-VACM-MIB", "NOTIFICATION-LOG-MIB",
    "RFC-1215", "RFC1155-SMI", "RFC1213-MIB", "RMON-MIB", "SCTP-MIB", "SMUX-MIB",
    "SNMP-COMMUNITY-MIB", "SNMP-FRAMEWORK-MIB", "SNMP-MPD-MIB", "SNMP-NOTIFICATION-MIB",
    "SNMP-PROXY-MIB", "SNMP-TARGET-MIB", "SNMP-TLS-TM-MIB", "SNMP-TSM-MIB",
    "SNMP-USER-BASED-SM-MIB", "SNMP-USM-AES-MIB", "SNMP-USM-DH-OBJECTS-MIB",
    "SNMP-USM-HMAC-SHA2-MIB", "SNMP-VIEW-BASED-ACM-MIB", "SNMPv2-CONF", "SNMPv2-MIB",
    "SNMPv2-SMI", "SNMPv2-TC", "SNMPv2-TM", "TCP-MIB", "TRANSPORT-ADDRESS-MIB",
    "TUNNEL-MIB", "UCD-DEMO-MIB", "UCD-DISKIO-MIB", "UCD-DLMOD-MIB", "UCD-IPFWACC-MIB",
    "UCD-SNMP-MIB", "UDP-MIB"
}


class MibManager:
    """Intelligent MIB manager handling workspace, resolution, lifecycle, and object discovery."""

    def __init__(self):
        self.loader = MIBLoader()
        # Keep track of active loaded module names
        self._active_modules: Set[str] = set()
        # Module name to MibFileInfo
        self._module_registry: Dict[str, MibFileInfo] = {}
        # Object symbol cache
        self._objects_cache: Dict[str, List[MibObjectInfo]] = {}

    def get_loader(self) -> MIBLoader:
        return self.loader

    def scan_mibs(self, directory: str = None) -> List[MibModuleInfo]:
        """Dynamically scan the application's MIB directory (or specified directory) for available MIB files."""
        modules = []
        loaded_set = set(self._active_modules)
        
        if directory:
            if os.path.isfile(directory):
                target_dir = os.path.dirname(os.path.abspath(directory))
            elif os.path.isdir(directory):
                target_dir = directory
            else:
                target_dir = self.loader.mib_dir
        else:
            target_dir = self.loader.mib_dir

        if not os.path.isdir(target_dir):
            return modules

        seen_names = set()

        # Dynamically scan only files physically present in the target MIB directory
        for filename in sorted(os.listdir(target_dir)):
            if filename.lower().endswith((".txt", ".mib", ".my")) or "." not in filename:
                fpath = os.path.join(target_dir, filename)
                if not os.path.isfile(fpath):
                    continue
                info = workspace_manager.parse_mib_header(fpath)
                if not info.is_valid_mib:
                    continue
                mod_name = info.module_name if info.module_name else filename.rsplit(".", 1)[0]
                if mod_name in seen_names:
                    continue
                seen_names.add(mod_name)
                self._module_registry[mod_name] = info
                
                is_loaded = mod_name in loaded_set
                is_bundled_rfc = mod_name in STANDARD_BUNDLED_MIBS
                rec = managed_registry.get_record(mod_name)
                is_managed = rec is not None and rec.is_managed
                orig_path = rec.original_path if rec else ""

                if is_bundled_rfc:
                    category = "packaged"
                elif is_managed:
                    category = "custom"
                else:
                    category = "packaged"

                status = "active" if is_loaded else "available"

                modules.append(MibModuleInfo(
                    name=mod_name,
                    path=fpath,
                    loaded=is_loaded,
                    status=status,
                    object_count=len(self._objects_cache.get(mod_name, [])),
                    dependencies=info.imports if info.is_valid_mib else [],
                    category=category,
                    is_managed=is_managed,
                    original_path=orig_path
                ))

        # When scanning the default application mibs folder, keep registry and active modules
        # synchronized with files actually present in the mibs folder.
        if not directory or os.path.normcase(os.path.abspath(target_dir)) == os.path.normcase(os.path.abspath(self.loader.mib_dir)):
            for active_mod in list(self._active_modules):
                if active_mod not in seen_names:
                    self._active_modules.discard(active_mod)
                    self.loader._loaded_modules.discard(active_mod)
                    self.loader._compile_status.pop(active_mod, None)
                    self._objects_cache.pop(active_mod, None)
            for reg_mod in list(self._module_registry.keys()):
                if reg_mod not in seen_names:
                    self._module_registry.pop(reg_mod, None)

        return modules

    def load_file(self, src_path: str) -> Dict[str, any]:
        """
        Loads an arbitrary MIB file (or directory of MIB files):
        1. Determines whether file is inside the application's packaged MIB directory.
        2. Stages canonical alias to workspace so PySMI compiler can always find it by module name.
        3. If external:
           - Preserves original file untouched at its current location.
           - Checks destination collision against existing unmanaged files.
           - Safely copies file to Net-SNMP application MIB directory (BUNDLED_MIBS_DIR).
           - Explicitly registers managed copies in ManagedCopyRegistry.
        4. If already packaged, avoids creating duplicate copies.
        5. Resolves dependencies (and safely handles external dependencies).
        6. Compiles and activates module.
        7. On failure, cleanly rolls back newly created copies so no unmanaged files linger.
        """
        if os.path.isdir(src_path):
            loaded_mods = []
            errors = []
            for fname in sorted(os.listdir(src_path)):
                if fname.lower().endswith((".txt", ".mib", ".my")) or "." not in fname:
                    fpath = os.path.join(src_path, fname)
                    if os.path.isfile(fpath):
                        info = workspace_manager.parse_mib_header(fpath)
                        if info.is_valid_mib:
                            res = self.load_file(fpath)
                            if res.get("success"):
                                loaded_mods.append(info.module_name)
                            else:
                                errors.append(res.get("message", fname))
            if loaded_mods:
                return {
                    "success": True,
                    "message": f"Loaded {len(loaded_mods)} MIB module(s) from directory: {', '.join(loaded_mods)}",
                    "module_name": loaded_mods[0],
                    "loaded_modules": loaded_mods,
                }
            err_detail = f" ({errors[0]})" if errors else ""
            return {"success": False, "message": f"No valid MIB files could be loaded from directory: {src_path}{err_detail}"}

        if not os.path.isfile(src_path):
            return {"success": False, "message": f"File not found: {src_path}"}

        file_info = workspace_manager.parse_mib_header(src_path)
        if not file_info.is_valid_mib:
            return {"success": False, "message": f"File is not a valid ASN.1 MIB: {src_path}"}

        # Stage canonical alias to workspace so PySMI can always find it
        try:
            workspace_manager.stage_file_to_workspace(src_path)
        except Exception as e:
            print(f"Warning: staging to workspace failed: {e}")

        is_external = not is_in_directory(src_path, BUNDLED_MIBS_DIR)
        newly_copied_modules = []

        if is_external:
            dest_filename = os.path.basename(src_path)
            dest_path = os.path.join(BUNDLED_MIBS_DIR, dest_filename)
            dest_paths = [dest_path]
            canonical_path = None
            if file_info.module_name:
                canonical_path = os.path.join(BUNDLED_MIBS_DIR, f"{file_info.module_name}.mib")
                if os.path.abspath(canonical_path) != os.path.abspath(dest_path):
                    dest_paths.append(canonical_path)

            # Check collision against existing unmanaged files
            ok, collision_err = managed_registry.check_destination_collision(src_path, dest_paths)
            if not ok:
                return {"success": False, "message": collision_err}

            # Safe copy to Net-SNMP directory (never move, rename, or delete original)
            try:
                if os.path.abspath(src_path) != os.path.abspath(dest_path):
                    shutil.copy2(src_path, dest_path)
                if canonical_path and os.path.abspath(dest_path) != os.path.abspath(canonical_path):
                    shutil.copy2(dest_path, canonical_path)
            except Exception as e:
                # Cleanup if copy failed partway
                for p in dest_paths:
                    if os.path.isfile(p) and not managed_registry.is_managed_copy(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass
                return {"success": False, "message": f"Failed to copy MIB to Net-SNMP directory: {e}"}

            # Register as managed copy
            managed_registry.register_copy(
                module_name=file_info.module_name,
                original_path=src_path,
                copied_paths=dest_paths,
                loaded=False
            )
            newly_copied_modules.append(file_info.module_name)

            # Point file_info to the available copied file
            file_info.filepath = dest_path
            file_info.filename = dest_filename

        # Resolve dependencies
        parent_dir = os.path.dirname(os.path.abspath(src_path))
        load_order, resolved_files, missing = dependency_resolver.resolve_dependencies(
            file_info, extra_source_dir=parent_dir
        )

        if missing:
            # Roll back newly copied files to maintain consistent state
            for mod in newly_copied_modules:
                managed_registry.safe_delete_managed_copies(mod, expected_base_dir=BUNDLED_MIBS_DIR)
                workspace_manager.remove_from_workspace(mod)
            return {
                "success": False,
                "message": f"Missing dependencies for {file_info.module_name}: {', '.join(missing)}",
                "missing": missing,
                "module_name": file_info.module_name
            }

        # Also stage any external dependencies resolved from parent_dir
        for dep_path in resolved_files:
            try:
                workspace_manager.stage_file_to_workspace(dep_path)
            except Exception:
                pass
            if not is_in_directory(dep_path, BUNDLED_MIBS_DIR):
                dep_info = workspace_manager.parse_mib_header(dep_path)
                if dep_info.is_valid_mib and dep_info.module_name != file_info.module_name:
                    dep_name = os.path.basename(dep_path)
                    dep_dest = os.path.join(BUNDLED_MIBS_DIR, dep_name)
                    dep_paths = [dep_dest]
                    dep_canon = os.path.join(BUNDLED_MIBS_DIR, f"{dep_info.module_name}.mib")
                    if os.path.abspath(dep_canon) != os.path.abspath(dep_dest):
                        dep_paths.append(dep_canon)
                    dep_ok, _ = managed_registry.check_destination_collision(dep_path, dep_paths)
                    if dep_ok:
                        try:
                            if os.path.abspath(dep_path) != os.path.abspath(dep_dest):
                                shutil.copy2(dep_path, dep_dest)
                            if os.path.abspath(dep_dest) != os.path.abspath(dep_canon):
                                shutil.copy2(dep_dest, dep_canon)
                            managed_registry.register_copy(
                                module_name=dep_info.module_name,
                                original_path=dep_path,
                                copied_paths=dep_paths,
                                loaded=False
                            )
                            newly_copied_modules.append(dep_info.module_name)
                        except Exception:
                            pass

        # Load / compile modules in order
        compiler = self.loader._get_compiler()
        import pysmi.reader.localfile as lf
        compiler.add_sources(lf.FileReader(workspace_manager.workspace_dir))
        compiler.add_sources(lf.FileReader(BUNDLED_MIBS_DIR))
        compiler.add_sources(lf.FileReader(parent_dir))

        compile_result = {}
        for mod in load_order:
            res = compiler.compile(mod)
            compile_result.update(res)

        target_mod = file_info.module_name
        target_status = compile_result.get(target_mod, "")
        if target_status in ("missing", "failed"):
            # Roll back on compilation failure
            for mod in newly_copied_modules:
                managed_registry.safe_delete_managed_copies(mod, expected_base_dir=BUNDLED_MIBS_DIR)
                workspace_manager.remove_from_workspace(mod)
            self._active_modules.discard(target_mod)
            self.loader._loaded_modules.discard(target_mod)
            return {
                "success": False,
                "message": f"Compilation failed for {target_mod}: status is '{target_status}'",
                "compile_status": compile_result
            }

        for mod in load_order:
            if compile_result.get(mod) in ("compiled", "untouched"):
                self._active_modules.add(mod)
                self.loader._loaded_modules.add(mod)
                if managed_registry.is_managed_module(mod):
                    managed_registry.update_loaded_state(mod, loaded=True)

        self.loader._compile_status.update(compile_result)
        self._active_modules.add(target_mod)
        self.loader._loaded_modules.add(target_mod)
        self._module_registry[target_mod] = file_info
        if managed_registry.is_managed_module(target_mod):
            managed_registry.update_loaded_state(target_mod, loaded=True)

        # Extract object catalog for discovery
        self.discover_objects(target_mod, [workspace_manager.workspace_dir, BUNDLED_MIBS_DIR, parent_dir], force=True)

        return {
            "success": True,
            "message": f"Successfully loaded {target_mod} with {len(load_order)} dependencies",
            "module_name": target_mod,
            "load_order": load_order,
            "compile_status": compile_result
        }

    def load_module(self, module_name: str, source_dir: str = None) -> Dict[str, any]:
        """Loads a MIB module by name, finding its file if necessary."""
        # Check if already active
        if module_name in self._active_modules:
            return {"success": True, "message": f"Module '{module_name}' is already loaded and active."}

        # 1. Search in module registry
        candidate_file = None
        if module_name in self._module_registry:
            cand = self._module_registry[module_name].filepath
            if cand and os.path.isfile(cand):
                candidate_file = cand

        # 2. Search search directories
        if not candidate_file:
            search_dirs = [source_dir] if source_dir else []
            search_dirs.extend([workspace_manager.workspace_dir, BUNDLED_MIBS_DIR, self.loader.mib_dir])
            for sdir in search_dirs:
                if not sdir or not os.path.isdir(sdir):
                    continue
                for fname in os.listdir(sdir):
                    fpath = os.path.join(sdir, fname)
                    if os.path.isfile(fpath):
                        base = fname.rsplit(".", 1)[0]
                        if base == module_name:
                            candidate_file = fpath
                            break
                        info = workspace_manager.parse_mib_header(fpath)
                        if info.is_valid_mib and info.module_name == module_name:
                            candidate_file = fpath
                            break
                if candidate_file:
                    break

        if candidate_file:
            return self.load_file(candidate_file)

        # 3. Fallback to compiler load
        res = self.loader.load_module(module_name, source_dir)
        status = res.get(module_name, "missing")
        if status in ("compiled", "untouched"):
            self._active_modules.add(module_name)
            self.discover_objects(module_name, [source_dir] if source_dir else None, force=True)
            return {"success": True, "message": f"Successfully loaded {module_name}", "compile_status": res}
        else:
            self._active_modules.discard(module_name)
            return {"success": False, "message": f"Compilation failed for {module_name}: status is '{status}'", "compile_status": res}

    def unload_module(self, module_name: str) -> Dict[str, any]:
        """
        Unload module from the application's active context.
        Checks if another active module depends on it.
        Deactivates from active runtime memory.
        If it's an application-managed copy, removes copy from Net-SNMP directory
        (as long as no other active module requires it as shared dependency).
        User's original file is never deleted or modified.
        Packaged files are never deleted from disk.
        """
        was_active = module_name in self._active_modules

        # Dependency check: does any other active module depend on module_name?
        dependents = []
        for mod, info in self._module_registry.items():
            if mod != module_name and mod in self._active_modules:
                if module_name in info.imports:
                    dependents.append(mod)

        if dependents:
            return {
                "success": False,
                "message": f"Cannot unload '{module_name}': required by active module(s): {', '.join(dependents)}",
                "dependents": dependents
            }

        # Remove from active sets
        self._active_modules.discard(module_name)
        self.loader._loaded_modules.discard(module_name)
        self.loader._compile_status.pop(module_name, None)
        self._objects_cache.pop(module_name, None)

        if module_name in self._module_registry:
            stem = self._module_registry[module_name].filename.rsplit(".", 1)[0]
            self.loader._loaded_modules.discard(stem)
            self.loader._compile_status.pop(stem, None)

        # Check if managed by application
        rec = managed_registry.get_record(module_name)
        if rec and rec.is_managed:
            # Check if this module is a shared dependency of another active module
            shared_dep = False
            for mod, info in self._module_registry.items():
                if mod in self._active_modules and module_name in info.imports:
                    shared_dep = True
                    break

            if not shared_dep:
                deleted_paths = managed_registry.safe_delete_managed_copies(
                    module_name, expected_base_dir=BUNDLED_MIBS_DIR
                )
                workspace_manager.remove_from_workspace(module_name)
                self._module_registry.pop(module_name, None)

                # Clean compiled py / pyc
                cache_dir = self.loader.get_cache_dir()
                for ext in [".py", ".pyc"]:
                    p = os.path.join(cache_dir, f"{module_name}{ext}")
                    if os.path.isfile(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass

                return {
                    "success": True,
                    "message": f"Module '{module_name}' unloaded and application-managed copy removed from Net-SNMP MIB directory (original file untouched).",
                    "deleted_paths": deleted_paths
                }
            else:
                managed_registry.update_loaded_state(module_name, loaded=False)
                return {
                    "success": True,
                    "message": f"Module '{module_name}' deactivated from active runtime (file preserved as shared dependency)."
                }
        else:
            # Packaged MIB: clean workspace alias so it is purely staged, never delete packaged file
            workspace_manager.remove_from_workspace(module_name)
            msg = f"Module '{module_name}' unloaded successfully." if was_active else f"Module '{module_name}' is already unloaded."
            return {
                "success": True,
                "message": msg
            }

    def _is_bundled_rfc_mib(self, name_or_file: str) -> bool:
        base = os.path.basename(name_or_file).rsplit(".", 1)[0]
        return base in STANDARD_BUNDLED_MIBS

    def remove_module(self, module_name: str) -> Dict[str, any]:
        """
        Completely remove a custom MIB from application and workspace:
        1. Checks dependents; refuses removal if an active module requires it.
        2. Deactivates from active runtime memory.
        3. Removes application-managed copies from Net-SNMP directory (never deleting user's original file).
        4. Removes staged files and canonical aliases from workspace.
        5. Cleans compiled py/pyc cache.
        6. Protects standard bundled RFC MIBs and packaged files from disk deletion.
        """
        # Dependency check
        dependents = []
        for mod, info in self._module_registry.items():
            if mod != module_name and mod in self._active_modules:
                if module_name in info.imports:
                    dependents.append(mod)

        if dependents:
            return {
                "success": False,
                "message": f"Cannot remove '{module_name}': required by active module(s): {', '.join(dependents)}",
                "dependents": dependents
            }

        # Deactivate from active runtime
        self._active_modules.discard(module_name)
        self.loader._loaded_modules.discard(module_name)
        self.loader._compile_status.pop(module_name, None)
        self._objects_cache.pop(module_name, None)

        if module_name in self._module_registry:
            stem = self._module_registry[module_name].filename.rsplit(".", 1)[0]
            self.loader._loaded_modules.discard(stem)
            self.loader._compile_status.pop(stem, None)

        # Remove from workspace
        workspace_manager.remove_from_workspace(module_name)

        # Clean compiled py/pyc
        cache_dir = self.loader.get_cache_dir()
        for ext in [".py", ".pyc"]:
            p = os.path.join(cache_dir, f"{module_name}{ext}")
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

        deleted_paths = []
        # If managed copy, delete from Net-SNMP MIB directory (never original)
        if managed_registry.is_managed_module(module_name):
            del_paths = managed_registry.safe_delete_managed_copies(module_name, expected_base_dir=BUNDLED_MIBS_DIR)
            deleted_paths.extend(del_paths)

        # Also remove any custom (non-standard RFC) files belonging to module_name in BUNDLED_MIBS_DIR
        if not self._is_bundled_rfc_mib(module_name) and os.path.isdir(BUNDLED_MIBS_DIR):
            std_lower = {s.lower() for s in STANDARD_BUNDLED_MIBS}
            target_lower = module_name.strip().lower()
            for fname in list(os.listdir(BUNDLED_MIBS_DIR)):
                fpath = os.path.join(BUNDLED_MIBS_DIR, fname)
                if not os.path.isfile(fpath):
                    continue
                base = fname.rsplit(".", 1)[0].lower()
                if base in std_lower:
                    continue  # Strictly protect standard bundled RFC MIBs from deletion!

                should_remove = False
                if fname.lower() == target_lower or base == target_lower:
                    should_remove = True
                else:
                    info = workspace_manager.parse_mib_header(fpath)
                    if info.is_valid_mib and info.module_name and info.module_name.lower() == target_lower:
                        should_remove = True

                if should_remove:
                    try:
                        os.remove(fpath)
                        deleted_paths.append(fpath)
                    except Exception as e:
                        print(f"Warning: Failed to remove custom copy {fpath}: {e}")

        self._module_registry.pop(module_name, None)
        for k in list(self._module_registry.keys()):
            if k.lower() == module_name.lower():
                self._module_registry.pop(k, None)

        if self._is_bundled_rfc_mib(module_name):
            return {
                "success": True,
                "message": f"Standard MIB '{module_name}' is bundled with the system and cannot be deleted from disk; it has been deactivated from active memory."
            }

        return {
            "success": True,
            "message": f"Module '{module_name}' removed from application and workspace (original file untouched).",
            "deleted_paths": deleted_paths
        }

    def reload_module(self, module_name: str) -> Dict[str, any]:
        """Reloads a module from its source, preserving clean state."""
        candidate_file = None

        if module_name in self._module_registry:
            cand = self._module_registry[module_name].filepath
            if cand and os.path.isfile(cand):
                candidate_file = cand

        if not candidate_file:
            rec = managed_registry.get_record(module_name)
            if rec:
                for cp in rec.copied_paths:
                    if os.path.isfile(cp):
                        candidate_file = cp
                        break
                if not candidate_file and os.path.isfile(rec.original_path):
                    candidate_file = rec.original_path

        if not candidate_file:
            self.scan_mibs()
            if module_name in self._module_registry:
                candidate_file = self._module_registry[module_name].filepath

        if not candidate_file or not os.path.isfile(candidate_file):
            return {"success": False, "message": f"Source file for '{module_name}' not found on disk."}

        # Clear object cache and previous compiled status
        self._objects_cache.pop(module_name, None)
        self.loader._compile_status.pop(module_name, None)

        res = self.load_file(candidate_file)
        if not res.get("success"):
            self._active_modules.discard(module_name)
            return {"success": False, "message": f"Reload failed: {res.get('message')}"}

        parent_dir = os.path.dirname(os.path.abspath(candidate_file))
        self.discover_objects(module_name, [workspace_manager.workspace_dir, BUNDLED_MIBS_DIR, parent_dir], force=True)
        return {"success": True, "message": f"Module '{module_name}' reloaded successfully."}

    def unload_all(self) -> Dict[str, any]:
        """Unload all application-managed MIB modules (original source files safe)."""
        active_list = list(self._active_modules)
        managed_list = [rec.module_name for rec in managed_registry.list_all() if rec.is_managed]
        all_to_unload = list(set(active_list + managed_list))

        for mod in all_to_unload:
            if managed_registry.is_managed_module(mod):
                managed_registry.safe_delete_managed_copies(mod, expected_base_dir=BUNDLED_MIBS_DIR)
                workspace_manager.remove_from_workspace(mod)
                cache_dir = self.loader.get_cache_dir()
                for ext in [".py", ".pyc"]:
                    p = os.path.join(cache_dir, f"{mod}{ext}")
                    if os.path.isfile(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass
            else:
                workspace_manager.remove_from_workspace(mod)

        count = len(self._active_modules)
        self._active_modules.clear()
        self.loader._loaded_modules.clear()
        self.loader._compile_status.clear()
        self._objects_cache.clear()
        return {"success": True, "message": f"Unloaded {count} modules from application (original files untouched)."}


    def discover_objects(self, module_name: str, extra_dirs: Optional[List[str]] = None, force: bool = False) -> List[MibObjectInfo]:
        """Extract and cache MIB object definitions for a module."""
        if not force and module_name in self._objects_cache:
            return self._objects_cache[module_name]

        # Use pysnmp MibBuilder or snmptranslate
        from pysnmp.smi.builder import MibBuilder, DirMibSource
        builder = MibBuilder()
        builder.add_mib_sources(DirMibSource(self.loader.get_cache_dir()))
        if extra_dirs:
            for ed in extra_dirs:
                if os.path.isdir(ed):
                    try:
                        builder.add_mib_sources(DirMibSource(ed))
                    except Exception:
                        pass
        try:
            builder.load_modules(module_name)
        except Exception:
            pass

        mod_symbols = builder.mibSymbols.get(module_name, {})
        objects = []
        for sym_name, sym_obj in mod_symbols.items():
            try:
                if not hasattr(sym_obj, "getName") or not callable(getattr(sym_obj, "getName")):
                    continue
                if isinstance(sym_obj, type):
                    continue
                oid_tuple = sym_obj.getName()
                if not isinstance(oid_tuple, (tuple, list)):
                    continue
                oid_str = ".".join(str(x) for x in oid_tuple)

                syntax_cls = getattr(sym_obj, "syntax", None)
                syntax = syntax_cls.__class__.__name__ if syntax_cls is not None else ""
                max_access = getattr(sym_obj, "maxAccess", "read-only")
                description = getattr(sym_obj, "description", "")

                enums = {}
                if hasattr(syntax_cls, "namedValues") and syntax_cls.namedValues:
                    try:
                        for k, v in syntax_cls.namedValues.items():
                            enums[str(k)] = int(v)
                    except Exception:
                        pass

                mro_names = [c.__name__ for c in type(sym_obj).__mro__]
                is_table = "MibTable" in mro_names or "Table" in sym_name
                is_entry = "MibTableRow" in mro_names or "Entry" in sym_name
                is_column = "MibTableColumn" in mro_names or (not is_entry and not is_table and ("Row" in sym_name or "Index" in sym_name or "read-create" in str(max_access)))

                obj_info = MibObjectInfo(
                    name=sym_name,
                    oid=oid_str,
                    module=module_name,
                    syntax=str(syntax),
                    max_access=str(max_access),
                    status="current",
                    description=str(description),
                    enums=enums,
                    is_table=is_table,
                    is_column=is_column
                )
                objects.append(obj_info)
            except Exception:
                continue

        self._objects_cache[module_name] = objects
        return objects

    def search_objects(self, query: str = "", module_filter: str = "") -> List[MibObjectInfo]:
        """Search discovered MIB objects by query and module."""
        results = []
        query_lower = query.lower().strip()
        modules_to_search = [module_filter] if module_filter else list(self._objects_cache.keys())

        # Ensure cache is populated for all active modules
        for mod in list(self._active_modules):
            if mod not in self._objects_cache:
                self.discover_objects(mod)

        for mod in modules_to_search:
            for obj in self._objects_cache.get(mod, []):
                if not query_lower:
                    results.append(obj)
                elif (
                    query_lower in obj.name.lower()
                    or query_lower in obj.oid
                    or query_lower in obj.module.lower()
                    or query_lower in obj.description.lower()
                ):
                    results.append(obj)
        return results

    def get_tree(self) -> List[dict]:
        """Construct a hierarchical MIB tree structure from discovered objects."""
        # Ensure objects cache is populated for all active modules
        for mod in list(self._active_modules):
            if mod not in self._objects_cache:
                self.discover_objects(mod)

        # Standard MIB-II / SMI root placeholders if missing
        standard_nodes = {
            "1": {"name": "iso", "oid": "1", "sub_id": 1, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
            "1.3": {"name": "org", "oid": "1.3", "sub_id": 3, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
            "1.3.6": {"name": "dod", "oid": "1.3.6", "sub_id": 6, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
            "1.3.6.1": {"name": "internet", "oid": "1.3.6.1", "sub_id": 1, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
            "1.3.6.1.1": {"name": "directory", "oid": "1.3.6.1.1", "sub_id": 1, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
            "1.3.6.1.2": {"name": "mgmt", "oid": "1.3.6.1.2", "sub_id": 2, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
            "1.3.6.1.2.1": {"name": "mib-2", "oid": "1.3.6.1.2.1", "sub_id": 1, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
            "1.3.6.1.3": {"name": "experimental", "oid": "1.3.6.1.3", "sub_id": 3, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
            "1.3.6.1.4": {"name": "private", "oid": "1.3.6.1.4", "sub_id": 4, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
            "1.3.6.1.4.1": {"name": "enterprises", "oid": "1.3.6.1.4.1", "sub_id": 1, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
            "1.3.6.1.5": {"name": "security", "oid": "1.3.6.1.5", "sub_id": 5, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
            "1.3.6.1.6": {"name": "snmpV2", "oid": "1.3.6.1.6", "sub_id": 6, "syntax": "", "max_access": "", "is_table": False, "is_column": False, "children": []},
        }

        all_nodes = {k: dict(v, children=[]) for k, v in standard_nodes.items()}

        # Collect discovered objects from active modules only
        for mod in self._active_modules:
            objs = self._objects_cache.get(mod, [])
            for obj in objs:
                oid_parts = [int(p) for p in obj.oid.split(".") if p.isdigit()]
                sub_id = oid_parts[-1] if oid_parts else 0
                all_nodes[obj.oid] = {
                    "name": obj.name,
                    "oid": obj.oid,
                    "sub_id": sub_id,
                    "module": obj.module,
                    "syntax": obj.syntax,
                    "max_access": obj.max_access,
                    "enums": getattr(obj, "enums", {}),
                    "is_table": obj.is_table,
                    "is_column": obj.is_column,
                    "children": []
                }

        # Synthesize missing intermediate ancestor nodes so everything chains up to root (e.g. 1.3.6.1.4.1.841)
        for oid in list(all_nodes.keys()):
            parts = oid.split(".")
            for i in range(1, len(parts)):
                ancestor_oid = ".".join(parts[:i])
                if ancestor_oid not in all_nodes:
                    resolved = self.loader.resolve_oid(ancestor_oid)
                    label = resolved.split(".")[-1] if resolved and "." in resolved and not resolved.endswith(ancestor_oid) else ancestor_oid
                    sub_id = int(parts[i - 1]) if parts[i - 1].isdigit() else 0
                    all_nodes[ancestor_oid] = {
                        "name": label,
                        "oid": ancestor_oid,
                        "sub_id": sub_id,
                        "module": "",
                        "syntax": "",
                        "max_access": "",
                        "is_table": False,
                        "is_column": False,
                        "children": []
                    }

        # Wire parent-child relationships
        roots = []
        # Sort keys by OID arc length so parents come before children
        for oid in sorted(all_nodes.keys(), key=lambda x: [int(p) for p in x.split(".") if p.isdigit()]):
            node = all_nodes[oid]
            parts = oid.split(".")
            if len(parts) <= 1:
                roots.append(node)
                continue
            parent_oid = ".".join(parts[:-1])
            if parent_oid in all_nodes:
                all_nodes[parent_oid]["children"].append(node)
            else:
                roots.append(node)

        # Sort children of each node by sub_id
        def sort_children(n):
            n["children"].sort(key=lambda c: c.get("sub_id", 0))
            for c in n["children"]:
                sort_children(c)

        for r in roots:
            sort_children(r)

        return roots

    def get_loaded_modules(self) -> List[str]:
        return sorted(self._active_modules)

    def resolve_oid(self, oid: str) -> str:
        return self.loader.resolve_oid(oid)


mib_manager = MibManager()