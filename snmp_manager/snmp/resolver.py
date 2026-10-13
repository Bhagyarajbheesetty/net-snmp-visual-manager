import os
from typing import List, Dict, Optional, Tuple, Set
from snmp.workspace import MibFileInfo, workspace_manager, BUNDLED_MIBS_DIR


class DependencyResolver:
    r"""
    Recursively resolves MIB dependencies using deterministic search order:
    1. Application-bundled standard MIBs (C:\net-snmp\share\snmp\mibs)
    2. Managed MIB workspace (~/.snmp-manager/workspace/mibs)
    3. Directory containing the selected MIB file
    4. User-configured custom MIB search paths
    """

    def __init__(self, search_paths: Optional[List[str]] = None):
        self.search_paths = search_paths or []

    def get_effective_search_paths(self, extra_source_dir: Optional[str] = None) -> List[str]:
        paths = [
            BUNDLED_MIBS_DIR,
            workspace_manager.workspace_dir,
        ]
        if extra_source_dir and os.path.isdir(extra_source_dir):
            paths.append(extra_source_dir)
        for p in self.search_paths:
            if p and os.path.isdir(p) and p not in paths:
                paths.append(p)
        return [os.path.abspath(p) for p in paths if os.path.isdir(p)]

    def index_directory_modules(self, directory: str) -> Dict[str, str]:
        """Index a directory mapping module_name -> filepath."""
        module_map = {}
        if not os.path.isdir(directory):
            return module_map

        for fname in os.listdir(directory):
            # Only consider files with standard MIB extensions or extensionless files < 2MB
            lower = fname.lower()
            if not (lower.endswith((".txt", ".mib", ".my")) or "." not in fname):
                continue
            fpath = os.path.join(directory, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                if os.path.getsize(fpath) > 5 * 1024 * 1024:  # skip files > 5MB
                    continue
            except Exception:
                continue

            info = workspace_manager.parse_mib_header(fpath)
            if info.is_valid_mib and info.module_name:
                module_map[info.module_name] = fpath
            else:
                base = fname.rsplit(".", 1)[0]
                if base not in module_map and lower.endswith((".txt", ".mib", ".my")):
                    module_map[base] = fpath
        return module_map

    def resolve_dependencies(
        self,
        target_info: MibFileInfo,
        extra_source_dir: Optional[str] = None,
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Recursively resolves dependencies for target_info.
        Returns (load_order_module_names, resolved_filepaths, missing_dependencies).
        Detects circular dependencies safely.
        """
        search_dirs = self.get_effective_search_paths(extra_source_dir)
        
        # Build composite module index across search paths in reverse order so higher priority overrides
        composite_index: Dict[str, str] = {}
        for sdir in reversed(search_dirs):
            idx = self.index_directory_modules(sdir)
            composite_index.update(idx)

        # Make sure target itself is indexed
        if target_info.module_name:
            composite_index[target_info.module_name] = target_info.filepath

        load_order: List[str] = []
        resolved_files: List[str] = []
        missing: List[str] = []
        visited: Set[str] = set()
        visiting: Set[str] = set()

        def dfs(mod_name: str, chain: List[str]):
            if mod_name in visited:
                return
            if mod_name in visiting:
                # Cycle detected, log cycle chain but do not infinite loop
                print(f"Circular MIB dependency detected: {' -> '.join(chain + [mod_name])}")
                return

            visiting.add(mod_name)
            fpath = composite_index.get(mod_name)

            if not fpath or not os.path.isfile(fpath):
                if mod_name not in missing:
                    missing.append(mod_name)
                visiting.remove(mod_name)
                visited.add(mod_name)
                return

            # Parse imports for this module
            mod_info = workspace_manager.parse_mib_header(fpath)
            for imp in mod_info.imports:
                dfs(imp, chain + [mod_name])

            visiting.remove(mod_name)
            visited.add(mod_name)

            if mod_name not in load_order:
                load_order.append(mod_name)
            if fpath not in resolved_files:
                resolved_files.append(fpath)

        for imp in target_info.imports:
            dfs(imp, [target_info.module_name])

        # Finally add target itself
        if target_info.module_name not in load_order:
            load_order.append(target_info.module_name)
        if target_info.filepath not in resolved_files:
            resolved_files.append(target_info.filepath)

        return load_order, resolved_files, missing


dependency_resolver = DependencyResolver()
