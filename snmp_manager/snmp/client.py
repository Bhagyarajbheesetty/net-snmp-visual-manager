from pysnmp.hlapi.asyncio import (
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    UsmUserData,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmHMAC192SHA256AuthProtocol,
    usmDESPrivProtocol,
    usmAesCfb128Protocol,
    usmAesCfb256Protocol,
    get_cmd,
    next_cmd,
    bulk_cmd,
    walk_cmd,
    bulk_walk_cmd,
)
from pysnmp.smi.builder import MibBuilder, DirMibSource
from pysnmp.smi.view import MibViewController
from pysmi.compiler import MibCompiler
from pysmi.parser.smi import SmiV2Parser
from pysmi.codegen.pysnmp import PySnmpCodeGen
from pysmi.writer.pyfile import PyFileWriter
from pysmi.reader.localfile import FileReader
from pysmi.searcher.pyfile import PyFileSearcher
import asyncio
import os
from typing import List, Optional, Callable, Awaitable, Dict, Tuple
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DeviceConfig:
    ip: str
    port: int = 161
    community: str = "public"
    version: str = "v2c"
    retries: int = 2
    timeout: int = 2
    username: Optional[str] = None
    auth_protocol: Optional[str] = None
    auth_password: Optional[str] = None
    privacy_protocol: Optional[str] = None
    privacy_password: Optional[str] = None


@dataclass
class VarBind:
    oid: str
    name: str
    type: str
    value: str
    index: str = ""
    status: str = "ok"  # "ok" or "failed"
    error_msg: Optional[str] = None
    seq: int = 0
    display_value: Optional[str] = None
    display_type: Optional[str] = None


from snmp.workspace import BUNDLED_MIBS_DIR


class WindowsSafePyFileWriter(PyFileWriter):
    """
    Subclass of PyFileWriter that removes any pre-existing target .py/.pyc file before writing
    so that PyFileWriter's internal os.rename(tfile, pyfile) does not fail on Windows with
    [WinError 183] Cannot create a file when that file already exists.
    """

    def put_data(self, mibname, data, comments=(), dryRun=False):
        if not dryRun and os.path.exists(self._path):
            mod_str = mibname.decode("utf-8") if isinstance(mibname, bytes) else str(mibname)
            base_path = os.path.join(self._path, mod_str)
            for ext in (".py", ".pyc", ".pyo"):
                target_file = base_path + ext
                if os.path.exists(target_file):
                    try:
                        os.remove(target_file)
                    except OSError:
                        pass
            pycache_dir = os.path.join(self._path, "__pycache__")
            if os.path.isdir(pycache_dir):
                for fn in os.listdir(pycache_dir):
                    if fn.startswith(f"{mod_str}."):
                        try:
                            os.remove(os.path.join(pycache_dir, fn))
                        except OSError:
                            pass
        return super().put_data(mibname, data, comments=comments, dryRun=dryRun)


class MIBLoader:
    """Compiles ASN.1 MIB files to pysnmp Python modules using pysmi."""

    def __init__(self, mib_dir: str = None, cache_dir: str = None):
        self.mib_dir = mib_dir or BUNDLED_MIBS_DIR
        self.cache_dir = cache_dir or os.path.expanduser("~/.snmp-manager/mibs")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._compiler = None
        self._loaded_modules: set = set()
        self._compile_status: Dict[str, str] = {}

    def _get_compiler(self) -> MibCompiler:
        if self._compiler is None:
            self._compiler = MibCompiler(
                SmiV2Parser(),
                PySnmpCodeGen(),
                WindowsSafePyFileWriter(self.cache_dir),
            )
            self._compiler.add_sources(FileReader(self.mib_dir))
            self._compiler.add_searchers(PyFileSearcher(self.cache_dir))
        return self._compiler

    def _scan_mib_files(self, directory: str = None) -> List[str]:
        """Return list of module names found in a directory."""
        d = directory or self.mib_dir
        if not os.path.isdir(d):
            return []
        names = []
        for filename in sorted(os.listdir(d)):
            if filename.lower().endswith((".txt", ".mib", ".my")):
                names.append(filename.rsplit(".", 1)[0])
        return names

    def load_module(self, module_name: str, source_dir: str = None) -> Dict[str, str]:
        """Load a single MIB module. Returns dict of {module: status}."""
        try:
            compiler = self._get_compiler()
            if source_dir and source_dir != self.mib_dir:
                compiler.add_sources(FileReader(source_dir))
            result = compiler.compile(module_name)
            self._compile_status.update(result)
            # Mark as loaded if compiled or untouched (success states)
            status = result.get(module_name, "missing")
            if status in ("compiled", "untouched"):
                self._loaded_modules.add(module_name)
            return result
        except Exception as e:
            print(f"Failed to load MIB {module_name}: {e}")
            return {module_name: "error"}

    def load_all(self, source_dir: str = None) -> Dict[str, int]:
        """Load all MIB modules from a directory. Compiles together to resolve deps."""
        try:
            compiler = self._get_compiler()
            if source_dir and source_dir != self.mib_dir:
                compiler.add_sources(FileReader(source_dir))
                self.mib_dir = source_dir
            module_names = self._scan_mib_files()
            if not module_names:
                return {"compiled": 0, "untouched": 0, "failed": 0}
            # Compile all at once so pysmi resolves dependencies among them
            result = compiler.compile(*module_names)
            self._compile_status.update(result)
            counts = {"compiled": 0, "untouched": 0, "failed": 0}
            for mod, status in result.items():
                if status in ("compiled", "untouched"):
                    self._loaded_modules.add(mod)
                    counts["compiled" if status == "compiled" else "untouched"] += 1
                else:
                    counts["failed"] += 1
            return counts
        except Exception as e:
            print(f"Failed to load all MIBs: {e}")
            return {"compiled": 0, "untouched": 0, "failed": 0, "error": str(e)}

    def get_loaded_modules(self) -> List[str]:
        return sorted(self._loaded_modules)

    def get_cache_dir(self) -> str:
        return self.cache_dir

    def get_compile_status(self) -> Dict[str, str]:
        return dict(self._compile_status)

    def is_loaded(self, module_name: str) -> bool:
        return module_name in self._loaded_modules

    def resolve_oid(self, oid: str) -> str:
        """Resolve an OID to its symbolic name using compiled MIBs."""
        try:
            builder = MibBuilder()
            builder.add_mib_sources(DirMibSource(self.cache_dir))
            if self._loaded_modules:
                try:
                    builder.load_modules(*self._loaded_modules)
                except Exception:
                    pass
            view = MibViewController(builder)
            oid_tuple = tuple(int(x) for x in oid.split(".") if x)
            _, name_tuple, _ = view.get_node_name_by_oid(oid_tuple)
            if name_tuple:
                return ".".join(str(n) for n in name_tuple)
        except Exception as e:
            print(f"OID resolve failed for {oid}: {e}")
        return oid


class SNMPClient:
    def __init__(self, config: DeviceConfig, mib_loader: Optional[MIBLoader] = None):
        self.config = config
        self.engine = SnmpEngine()
        self.mib_loader = mib_loader
        self._mib_builder = None
        self._setup_mib_builder()

    def _setup_mib_builder(self):
        try:
            self._mib_builder = self.engine.get_mib_builder()
            cache_dir = self.mib_loader.get_cache_dir() if self.mib_loader else os.path.expanduser("~/.snmp-manager/mibs")
            if os.path.isdir(cache_dir):
                self._mib_builder.add_mib_sources(DirMibSource(cache_dir))
            loaded_mods = set()
            if self.mib_loader:
                loaded_mods.update(self.mib_loader.get_loaded_modules())
            try:
                from snmp.mib import mib_manager
                loaded_mods.update(mib_manager._active_modules)
            except Exception:
                pass
            loaded_mods.update(["SNMPv2-MIB", "SNMPv2-TC"])
            for mod in sorted(loaded_mods):
                try:
                    self._mib_builder.load_modules(mod)
                except Exception:
                    pass
            self._mib_view = MibViewController(self._mib_builder)
        except Exception as e:
            print(f"MIB builder setup warning: {e}")

    def _get_auth_data(self):
        if self.config.version == "v2c":
            return CommunityData(self.config.community, mpModel=1)
        elif self.config.version == "v1":
            return CommunityData(self.config.community, mpModel=0)
        elif self.config.version == "v3":
            if not self.config.username:
                raise ValueError("SNMPv3 requires a username")
            has_auth = bool(self.config.auth_password)
            has_priv = bool(self.config.privacy_password and has_auth)
            auth_protocol = self._get_pysnmp_auth(self.config.auth_protocol) if has_auth else None
            priv_protocol = self._get_pysnmp_priv(self.config.privacy_protocol) if has_priv else None
            return UsmUserData(
                self.config.username,
                authKey=self.config.auth_password if has_auth else None,
                privKey=self.config.privacy_password if has_priv else None,
                authProtocol=auth_protocol,
                privProtocol=priv_protocol,
            )
        else:
            raise ValueError(f"Unsupported version: {self.config.version}")

    def _get_pysnmp_auth(self, protocol: Optional[str]):
        """Map auth protocol name to pysnmp USM auth protocol constant."""
        auth_map = {
            "MD5": usmHMACMD5AuthProtocol,
            "SHA": usmHMACSHAAuthProtocol,
            "SHA256": usmHMAC192SHA256AuthProtocol,
        }
        return auth_map.get(protocol, None)

    def _get_pysnmp_priv(self, protocol: Optional[str]):
        """Map privacy protocol name to pysnmp USM priv protocol constant."""
        priv_map = {
            "DES": usmDESPrivProtocol,
            "AES": usmAesCfb128Protocol,
            "AES256": usmAesCfb256Protocol,
        }
        return priv_map.get(protocol, None)

    async def _get_transport_target(self):
        return await UdpTransportTarget.create(
            (self.config.ip, self.config.port),
            timeout=self.config.timeout,
            retries=self.config.retries,
        )

    async def get(self, oids: List[str]) -> List[VarBind]:
        auth = self._get_auth_data()
        target = await self._get_transport_target()
        context = ContextData()
        var_binds = [ObjectType(ObjectIdentity(oid)) for oid in oids]

        error_indication, error_status, error_index, var_bind_table = await get_cmd(
            self.engine, auth, target, context, *var_binds
        )

        return self._process_varbinds(error_indication, error_status, error_index, var_bind_table)

    async def walk(
        self,
        oid_from: str,
        oid_to: Optional[str] = None,
        progress_callback: Optional[Callable[[List[VarBind]], Awaitable[None]]] = None,
        stop_event: Optional[asyncio.Event] = None,
        expected_oids: Optional[List[str]] = None,
    ) -> List[VarBind]:
        auth = self._get_auth_data()
        target = await self._get_transport_target()
        context = ContextData()
        current_oid_str = oid_from
        end_oid_str = str(oid_to) if oid_to else None

        results: List[VarBind] = []
        consecutive_failures = 0

        while True:
            if stop_event and stop_event.is_set():
                break

            current_oid = ObjectIdentity(current_oid_str)
            try:
                error_indication, error_status, error_index, var_bind_table = await next_cmd(
                    self.engine, auth, target, context, ObjectType(current_oid), lexicographicMode=False
                )
            except Exception as e:
                error_indication = str(e)
                error_status = None
                var_bind_table = None

            if error_indication:
                consecutive_failures += 1
                err_str = str(error_indication)
                err_lower = err_str.lower()
                is_timeout = "timeout" in err_lower or "timedout" in err_lower or "timed out" in err_lower
                is_no_response = "noresponse" in err_lower or "no response" in err_lower
                reason = "Request timed out" if is_timeout else ("No response from agent" if is_no_response else f"SNMP Error: {err_str}")
                failed_name, failed_index = self._resolve_oid_and_index(current_oid_str)
                failed_vb = VarBind(
                    oid=current_oid_str,
                    name=failed_name,
                    type="UNANSWERED",
                    value=reason,
                    index=failed_index,
                    status="failed",
                    error_msg="Timeout" if is_timeout else reason,
                    seq=len(results) + 1,
                )
                results.append(failed_vb)
                if progress_callback:
                    await progress_callback([failed_vb])

                next_oid = None
                if expected_oids:
                    for exp_oid in expected_oids:
                        if self._oid_compare(exp_oid, current_oid_str) > 0:
                            if not end_oid_str or self._oid_compare(exp_oid, end_oid_str) <= 0:
                                next_oid = exp_oid
                                break
                if next_oid:
                    current_oid_str = next_oid
                    continue
                else:
                    if consecutive_failures >= 3 and not [r for r in results if r.status == "ok"]:
                        raise Exception(f"SNMP Error: {error_indication}")
                    break

            if error_status:
                consecutive_failures += 1
                err_str = error_status.prettyPrint()
                failed_name, failed_index = self._resolve_oid_and_index(current_oid_str)
                failed_vb = VarBind(
                    oid=current_oid_str,
                    name=failed_name,
                    type="UNANSWERED",
                    value=err_str,
                    index=failed_index,
                    status="failed",
                    error_msg=err_str,
                    seq=len(results) + 1,
                )
                results.append(failed_vb)
                if progress_callback:
                    await progress_callback([failed_vb])

                next_oid = None
                if expected_oids:
                    for exp_oid in expected_oids:
                        if self._oid_compare(exp_oid, current_oid_str) > 0:
                            if not end_oid_str or self._oid_compare(exp_oid, end_oid_str) <= 0:
                                next_oid = exp_oid
                                break
                if next_oid:
                    current_oid_str = next_oid
                    continue
                else:
                    break

            if not var_bind_table:
                break

            consecutive_failures = 0
            valid_batch = []
            reached_end = False
            for var_bind in var_bind_table:
                last_oid_str = str(var_bind[0])
                if end_oid_str:
                    if self._oid_compare(last_oid_str, end_oid_str) > 0:
                        reached_end = True
                        break
                    valid_batch.append(var_bind)
                    if self._oid_compare(last_oid_str, end_oid_str) == 0:
                        reached_end = True
                        break
                else:
                    if not self._is_sub_tree(last_oid_str, oid_from):
                        reached_end = True
                        break
                    valid_batch.append(var_bind)

            if not valid_batch:
                break

            batch = self._process_varbinds(None, None, None, valid_batch)
            for item in batch:
                item.seq = len(results) + 1
                results.append(item)

            if progress_callback and batch:
                await progress_callback(batch)

            if reached_end:
                break

            last_oid_str = results[-1].oid
            if last_oid_str == current_oid_str:
                break
            current_oid_str = last_oid_str

        return results

    async def bulk_walk(
        self,
        oid_from: str,
        oid_to: Optional[str] = None,
        progress_callback: Optional[Callable[[List[VarBind]], Awaitable[None]]] = None,
        stop_event: Optional[asyncio.Event] = None,
        expected_oids: Optional[List[str]] = None,
    ) -> List[VarBind]:
        auth = self._get_auth_data()
        target = await self._get_transport_target()
        context = ContextData()
        current_oid_str = oid_from
        end_oid_str = str(oid_to) if oid_to else None

        results: List[VarBind] = []
        max_repetitions = 10
        base_repetitions = 10
        consecutive_success = 0
        consecutive_failures = 0

        while True:
            if stop_event and stop_event.is_set():
                break

            current_oid = ObjectIdentity(current_oid_str)
            error_indication = None
            error_status = None
            var_bind_table = None

            # Attempt bulk_cmd with current max_repetitions
            if max_repetitions > 1:
                try:
                    error_indication, error_status, error_index, var_bind_table = await bulk_cmd(
                        self.engine, auth, target, context, 0, max_repetitions,
                        ObjectType(current_oid), lexicographicMode=False
                    )
                except Exception:
                    error_indication = "Request exception"

            # If multi-repetition failed or timed out, step down or use next_cmd
            if error_indication or max_repetitions == 1:
                consecutive_success = 0
                if max_repetitions > 2:
                    max_repetitions = 2
                    continue
                # Try single GETNEXT
                try:
                    error_indication, error_status, error_index, var_bind_table = await next_cmd(
                        self.engine, auth, target, context, ObjectType(current_oid), lexicographicMode=False
                    )
                except Exception as e:
                    error_indication = str(e)
                    error_status = None
                    var_bind_table = None

                if error_indication:
                    consecutive_failures += 1
                    err_str = str(error_indication)
                    err_lower = err_str.lower()
                    is_timeout = "timeout" in err_lower or "timedout" in err_lower or "timed out" in err_lower
                    is_no_response = "noresponse" in err_lower or "no response" in err_lower
                    reason = "Request timed out" if is_timeout else ("No response from agent" if is_no_response else f"SNMP Error: {err_str}")
                    failed_name, failed_index = self._resolve_oid_and_index(current_oid_str)
                    failed_vb = VarBind(
                        oid=current_oid_str,
                        name=failed_name,
                        type="UNANSWERED",
                        value=reason,
                        index=failed_index,
                        status="failed",
                        error_msg="Timeout" if is_timeout else reason,
                        seq=len(results) + 1,
                    )
                    results.append(failed_vb)
                    if progress_callback:
                        await progress_callback([failed_vb])

                    next_oid = None
                    if expected_oids:
                        for exp_oid in expected_oids:
                            if self._oid_compare(exp_oid, current_oid_str) > 0:
                                if not end_oid_str or self._oid_compare(exp_oid, end_oid_str) <= 0:
                                    next_oid = exp_oid
                                    break
                    if next_oid:
                        current_oid_str = next_oid
                        max_repetitions = 1
                        continue
                    else:
                        if consecutive_failures >= 3 and not [r for r in results if r.status == "ok"]:
                            raise Exception(f"SNMP Error: {error_indication}")
                        break
                max_repetitions = 1

            if error_status:
                consecutive_failures += 1
                err_str = error_status.prettyPrint()
                failed_name, failed_index = self._resolve_oid_and_index(current_oid_str)
                failed_vb = VarBind(
                    oid=current_oid_str,
                    name=failed_name,
                    type="UNANSWERED",
                    value=err_str,
                    index=failed_index,
                    status="failed",
                    error_msg=err_str,
                    seq=len(results) + 1,
                )
                results.append(failed_vb)
                if progress_callback:
                    await progress_callback([failed_vb])

                next_oid = None
                if expected_oids:
                    for exp_oid in expected_oids:
                        if self._oid_compare(exp_oid, current_oid_str) > 0:
                            if not end_oid_str or self._oid_compare(exp_oid, end_oid_str) <= 0:
                                next_oid = exp_oid
                                break
                if next_oid:
                    current_oid_str = next_oid
                    continue
                else:
                    break

            if not var_bind_table:
                break

            consecutive_failures = 0
            # Filter out out-of-scope varbinds
            valid_batch = []
            reached_end = False
            for var_bind in var_bind_table:
                last_oid_str = str(var_bind[0])
                if end_oid_str:
                    if self._oid_compare(last_oid_str, end_oid_str) > 0:
                        reached_end = True
                        break
                    valid_batch.append(var_bind)
                    if self._oid_compare(last_oid_str, end_oid_str) == 0:
                        reached_end = True
                        break
                else:
                    if not self._is_sub_tree(last_oid_str, oid_from):
                        reached_end = True
                        break
                    valid_batch.append(var_bind)

            if not valid_batch:
                break

            batch = self._process_varbinds(None, None, None, valid_batch)
            for item in batch:
                item.seq = len(results) + 1
                results.append(item)

            if progress_callback and batch:
                await progress_callback(batch)

            if reached_end:
                break

            # Advance current OID for next bulk request
            last_oid_str = results[-1].oid
            if last_oid_str == current_oid_str:
                break  # Prevent infinite loop if agent returns same OID
            current_oid_str = last_oid_str

            consecutive_success += 1
            # Slowly recover repetitions towards base only after 5 stable consecutive responses
            if consecutive_success >= 5 and max_repetitions < base_repetitions:
                max_repetitions = min(base_repetitions, max_repetitions + 2)
                consecutive_success = 0

        return results

    def _is_sub_tree(self, child_oid: str, parent_oid: str) -> bool:
        c_parts = [x for x in child_oid.split(".") if x]
        p_parts = [x for x in parent_oid.split(".") if x]
        if len(c_parts) < len(p_parts):
            return False
        return c_parts[:len(p_parts)] == p_parts

    def _process_varbinds(self, error_indication, error_status, error_index, var_bind_table) -> List[VarBind]:
        results = []
        if var_bind_table:
            for var_bind in var_bind_table:
                oid_str = str(var_bind[0])
                val = var_bind[1]
                name, index, display_type, display_value = self._resolve_varbind_details(oid_str, val)
                type_str = self._get_type_name(val)
                value_str = self._format_value(val)
                results.append(VarBind(
                    oid=oid_str,
                    name=name,
                    type=type_str,
                    value=value_str,
                    index=index,
                    display_type=display_type,
                    display_value=display_value,
                ))
        return results

    def _resolve_varbind_details(self, oid: str, val) -> Tuple[str, str, str, str]:
        """
        Resolves OID and value using loaded MIB definitions into:
        (name, index, display_type, display_value)
        """
        name = oid
        index = ""
        node = None
        syntax = None

        try:
            if hasattr(self, "_mib_view") and self._mib_view:
                obj_id = ObjectIdentity(oid)
                obj_id.resolve_with_mib(self._mib_view)
                sym = obj_id.get_mib_symbol()
                if sym and len(sym) >= 2 and sym[1]:
                    name = str(sym[1])
                    node = obj_id.get_mib_node()
                    if node and hasattr(node, "getName"):
                        node_oid = node.getName()
                        full_oid = tuple(int(x) for x in oid.split(".") if x)
                        if len(full_oid) >= len(node_oid) and full_oid[:len(node_oid)] == node_oid:
                            suffix = full_oid[len(node_oid):]
                            index = ".".join(str(x) for x in suffix)
                        elif len(sym) >= 3 and sym[2]:
                            index = ".".join(str(x) for x in sym[2])
                    elif len(sym) >= 3 and sym[2]:
                        index = ".".join(str(x) for x in sym[2])
                    if node:
                        syntax = getattr(node, "syntax", None)
        except Exception:
            pass

        # If name is still numeric OID, try fallback to mib_manager objects cache
        if name == oid:
            try:
                from snmp.mib import mib_manager
                full_parts = [int(x) for x in oid.split(".") if x]
                for mod_objs in mib_manager._objects_cache.values():
                    for obj in mod_objs:
                        obj_parts = [int(x) for x in obj.oid.split(".") if x]
                        if len(full_parts) >= len(obj_parts) and full_parts[:len(obj_parts)] == obj_parts:
                            name = obj.name
                            index = ".".join(str(x) for x in full_parts[len(obj_parts):])
                            break
                    if name != oid:
                        break
            except Exception:
                pass

        display_type, display_value = self._decode_mib_value(name, syntax, val)
        return name, index, display_type, display_value

    def _decode_mib_value(self, name: str, syntax, val) -> Tuple[str, str]:
        rfc2579_row_status = {
            1: "active",
            2: "notInService",
            3: "notReady",
            4: "createAndGo",
            5: "createAndWait",
            6: "destroy",
        }

        s_cls = type(syntax).__name__ if syntax is not None else ""
        mro_names = [b.__name__ for b in type(syntax).__mro__] if syntax is not None else []
        has_nv = bool(getattr(syntax, "namedValues", None)) and len(syntax.namedValues) > 0

        # Check for RowStatus
        if s_cls == "RowStatus" or "RowStatus" in mro_names or (name and (name.endswith("EntryStatus") or name.endswith("RowStatus")) and s_cls in ("Integer32", "INTEGER", "")):
            try:
                num = int(val)
                lbl = rfc2579_row_status.get(num)
                display_value = f"{lbl} ({num})" if lbl else f"({num}) is not in any MIB!"
            except Exception:
                display_value = self._format_value(val)
            return "RowStatus", display_value

        # Check for Enumeration
        if has_nv and s_cls not in ("BitString", "Bits"):
            try:
                num = int(val)
                lbl = syntax.namedValues.getName(num)
                if lbl is not None and str(lbl).strip():
                    display_value = f"{lbl} ({num})"
                else:
                    display_value = f"({num}) is not in any MIB!"
            except Exception:
                display_value = self._format_value(val)
            return "Enum", display_value

        # Check for MacAddress / PhysAddress
        if s_cls in ("MacAddress", "PhysAddress") or "MacAddress" in mro_names or "PhysAddress" in mro_names or (name and any(name.endswith(x) for x in ("MacAddress", "MacAddr", "PhysAddress"))):
            display_type = "MacAddress" if ("MacAddress" in mro_names or s_cls == "MacAddress" or (name and "Mac" in name)) else (s_cls or "MacAddress")
            display_value = self._format_mac_address(val)
            return display_type, display_value

        # Check for TimeTicks
        if s_cls == "TimeTicks" or "TimeTicks" in mro_names or val.__class__.__name__ == "TimeTicks":
            return "TimeTicks", self._format_timeticks(val)

        # Check for DisplayString
        if s_cls == "DisplayString" or "DisplayString" in mro_names:
            return "DisplayString", self._format_value(val)

        # Check for Unsigned32
        if s_cls == "Unsigned32" or "Unsigned32" in mro_names:
            return "Unsigned32", self._format_value(val)

        # Generic MIB syntax if defined
        if s_cls and s_cls not in ("type", "object", "MibTableColumn", "MibScalar"):
            return s_cls, self._format_value(val)

        # Fallback to protocol type and value
        proto_type = self._get_type_name(val)
        return proto_type, self._format_value(val)

    def _format_mac_address(self, val) -> str:
        try:
            if hasattr(val, "asNumbers"):
                nums = list(val.asNumbers())
                if len(nums) == 6:
                    return ":".join(f"{b:02x}" for b in nums)
            if isinstance(val, (bytes, bytearray)):
                if len(val) == 6:
                    return ":".join(f"{b:02x}" for b in val)
            s = str(val).strip()
            clean = s.lower().removeprefix("0x")
            if len(clean) == 12 and all(c in "0123456789abcdef" for c in clean):
                return ":".join(clean[i:i+2] for i in range(0, 12, 2))
        except Exception:
            pass
        return self._format_value(val)

    def _format_timeticks(self, val) -> str:
        try:
            ticks = int(val)
            days = ticks // 8640000
            rem = ticks % 8640000
            hours = rem // 360000
            rem %= 360000
            mins = rem // 6000
            rem %= 6000
            secs = rem // 100
            cs = rem % 100
            return f"{days}-{hours}:{mins}:{secs}.{cs:02d}"
        except Exception:
            return self._format_value(val)

    def _resolve_oid_and_index(self, oid: str):
        name, index, _, _ = self._resolve_varbind_details(oid, None)
        return name, index

    def _resolve_oid_name(self, oid: str) -> str:
        name, _ = self._resolve_oid_and_index(oid)
        return name

    def _get_type_name(self, val) -> str:
        type_map = {
            "Integer": "Integer32",
            "Integer32": "Integer32",
            "Unsigned32": "Unsigned32",
            "Gauge32": "Gauge32",
            "Counter32": "Counter32",
            "Counter64": "Counter64",
            "OctetString": "OctetString",
            "DisplayString": "DisplayString",
            "IpAddress": "IpAddress",
            "TimeTicks": "TimeTicks",
            "ObjectName": "ObjectName",
            "BitString": "BitString",
        }
        cls_name = val.__class__.__name__
        return type_map.get(cls_name, cls_name)

    def _format_value(self, val) -> str:
        try:
            # Smart decoding for null-padded / null-terminated C-strings in OctetString
            if hasattr(val, "asOctets"):
                raw_bytes = val.asOctets()
                if b"\x00" in raw_bytes:
                    text_part = raw_bytes.split(b"\x00")[0]
                    if len(text_part) > 0 and all(32 <= b <= 126 or b in (9, 10, 13) for b in text_part):
                        return text_part.decode("utf-8", errors="replace")
            if hasattr(val, "prettyPrint"):
                return val.prettyPrint()
        except Exception:
            pass
        return str(val)

    def _extract_index(self, oid: str, name: str) -> str:
        _, index = self._resolve_oid_and_index(oid)
        return index

    def _oid_compare(self, oid1: str, oid2: str) -> int:
        try:
            parts1 = [int(x) for x in oid1.split(".") if x]
            parts2 = [int(x) for x in oid2.split(".") if x]
        except ValueError:
            return 0
        for a, b in zip(parts1, parts2):
            if a < b:
                return -1
            if a > b:
                return 1
        if len(parts1) < len(parts2):
            return -1
        if len(parts1) > len(parts2):
            return 1
        return 0