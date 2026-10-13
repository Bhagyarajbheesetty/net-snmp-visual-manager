import os
import subprocess
from typing import List, Dict, Optional, Tuple
from snmp.workspace import BUNDLED_MIBS_DIR, NET_SNMP_BIN_DIR, workspace_manager


class NetSnmpProcessRunner:
    """Centralized process manager for Net-SNMP CLI executables."""

    def __init__(self, bin_dir: Optional[str] = None):
        self.bin_dir = bin_dir or NET_SNMP_BIN_DIR
        self.snmpget_exe = os.path.join(self.bin_dir, "snmpget.exe")
        self.snmpset_exe = os.path.join(self.bin_dir, "snmpset.exe")
        self.snmptranslate_exe = os.path.join(self.bin_dir, "snmptranslate.exe")
        self.snmpwalk_exe = os.path.join(self.bin_dir, "snmpwalk.exe")
        self.active_processes: set = set()

    def _get_silent_kwargs(self) -> dict:
        """Returns subprocess flags to completely suppress console/command window on Windows."""
        kwargs = {}
        if os.name == "nt" or sys.platform == "win32":
            # 0x08000000 is CREATE_NO_WINDOW
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                kwargs["startupinfo"] = startupinfo
            except Exception:
                pass
        return kwargs

    def check_binaries(self) -> Dict[str, bool]:
        return {
            "snmpget": os.path.isfile(self.snmpget_exe),
            "snmpset": os.path.isfile(self.snmpset_exe),
            "snmptranslate": os.path.isfile(self.snmptranslate_exe),
            "snmpwalk": os.path.isfile(self.snmpwalk_exe),
        }

    def get_mib_dirs_flag(self, extra_dirs: Optional[List[str]] = None) -> str:
        dirs = [BUNDLED_MIBS_DIR, workspace_manager.workspace_dir]
        if extra_dirs:
            for d in extra_dirs:
                if d and os.path.isdir(d) and d not in dirs:
                    dirs.append(d)
        # Use '+' prefix to append to default MIB dirs
        return "+" + ";".join(dirs)

    def _build_auth_args(self, device: dict) -> List[str]:
        version = device.get("version", "v2c")
        args = []
        if version == "v1":
            args.extend(["-v", "1", "-c", device.get("read_community", "public")])
        elif version == "v2c":
            args.extend(["-v", "2c", "-c", device.get("read_community", "public")])
        elif version == "v3":
            args.extend(["-v", "3", "-u", device.get("username", "admin")])
            auth_pass = device.get("auth_password")
            priv_pass = device.get("privacy_password")
            if auth_pass and priv_pass:
                args.extend(["-l", "authPriv"])
                args.extend(["-a", device.get("auth_protocol", "SHA")])
                args.extend(["-A", auth_pass])
                args.extend(["-x", device.get("privacy_protocol", "AES")])
                args.extend(["-X", priv_pass])
            elif auth_pass:
                args.extend(["-l", "authNoPriv"])
                args.extend(["-a", device.get("auth_protocol", "SHA")])
                args.extend(["-A", auth_pass])
            else:
                args.extend(["-l", "noAuthNoPriv"])
        else:
            raise ValueError(f"Unsupported SNMP version: {version}")

        # Timeout and retries
        timeout = device.get("timeout", 2)
        retries = device.get("retries", 2)
        args.extend(["-t", str(timeout), "-r", str(retries)])
        return args

    def run_snmpget(
        self,
        device: dict,
        oid: str,
        modules: Optional[List[str]] = None,
        extra_dirs: Optional[List[str]] = None,
    ) -> Tuple[bool, str, str]:
        """
        Executes snmpget.exe with safe argument array.
        Returns (success, stdout, stderr_or_error).
        """
        mod_str = ";".join(modules) if modules else "ALL"
        mib_dirs = self.get_mib_dirs_flag(extra_dirs)
        target = f"{device.get('ip_address')}:{device.get('port', 161)}"

        cmd = [self.snmpget_exe, "-m", mod_str, "-M", mib_dirs]
        cmd.extend(self._build_auth_args(device))
        cmd.extend([target, oid])

        proc_timeout = max(10, int(device.get("timeout", 2)) * (int(device.get("retries", 2)) + 1) + 5)
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                **self._get_silent_kwargs(),
            )
            self.active_processes.add(proc)
            try:
                stdout, stderr = proc.communicate(timeout=proc_timeout)
                if proc.returncode == 0:
                    return True, stdout.strip(), ""
                return False, stdout.strip(), stderr.strip()
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                return False, "", "Request timed out"
            finally:
                self.active_processes.discard(proc)
        except Exception as e:
            return False, "", str(e)

    def run_snmpset(
        self,
        device: dict,
        oid: str,
        snmp_type_char: str,
        value: str,
        modules: Optional[List[str]] = None,
        extra_dirs: Optional[List[str]] = None,
    ) -> Tuple[bool, str, str]:
        """
        Executes snmpset.exe with safe argument array.
        Returns (success, stdout, stderr_or_error).
        """
        mod_str = ";".join(modules) if modules else "ALL"
        mib_dirs = self.get_mib_dirs_flag(extra_dirs)
        target = f"{device.get('ip_address')}:{device.get('port', 161)}"

        # For SNMP SET write community is used for v1/v2c
        dev_copy = dict(device)
        if dev_copy.get("version") in ("v1", "v2c"):
            dev_copy["read_community"] = dev_copy.get("write_community") or dev_copy.get("read_community", "private")

        cmd = [self.snmpset_exe, "-m", mod_str, "-M", mib_dirs]
        cmd.extend(self._build_auth_args(dev_copy))
        cmd.extend([target, oid, snmp_type_char, value])

        proc_timeout = max(10, int(dev_copy.get("timeout", 2)) * (int(dev_copy.get("retries", 2)) + 1) + 5)
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                **self._get_silent_kwargs(),
            )
            self.active_processes.add(proc)
            try:
                stdout, stderr = proc.communicate(timeout=proc_timeout)
                if proc.returncode == 0:
                    return True, stdout.strip(), ""
                return False, stdout.strip(), stderr.strip()
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                return False, "", "Request timed out"
            finally:
                self.active_processes.discard(proc)
        except Exception as e:
            return False, "", str(e)

    def kill_all_processes(self) -> int:
        """Terminates all running Net-SNMP CLI processes spawned by this runner."""
        count = 0
        for proc in list(self.active_processes):
            try:
                proc.kill()
                count += 1
            except Exception:
                pass
        self.active_processes.clear()
        return count

    def kill_all_snmp_tasks(self):
        """Kills any active spawned processes and stray snmp executables on the system."""
        self.kill_all_processes()
        if os.name == "nt":
            for exe in ("snmpget.exe", "snmpset.exe", "snmpwalk.exe", "snmpbulkwalk.exe"):
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/IM", exe],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        timeout=3,
                        **self._get_silent_kwargs(),
                    )
                except Exception:
                    pass

    def run_snmpwalk(
        self,
        device: dict,
        oid: str,
        modules: Optional[List[str]] = None,
        extra_dirs: Optional[List[str]] = None,
        timeout_sec: int = 60,
    ) -> Tuple[bool, str, str]:
        """
        Executes snmpwalk.exe with safe argument array.
        Returns (success, stdout, stderr_or_error).
        """
        mod_str = ";".join(modules) if modules else "ALL"
        mib_dirs = self.get_mib_dirs_flag(extra_dirs)
        target = f"{device.get('ip_address')}:{device.get('port', 161)}"

        cmd = [self.snmpwalk_exe, "-m", mod_str, "-M", mib_dirs]
        cmd.extend(self._build_auth_args(device))
        cmd.extend([target, oid])

        try:
            res = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                **self._get_silent_kwargs(),
            )
            if res.returncode == 0:
                return True, res.stdout.strip(), ""
            return False, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "Request timed out"
        except Exception as e:
            return False, "", str(e)

    def translate_oid_details(
        self,
        oid_or_name: str,
        modules: Optional[List[str]] = None,
        extra_dirs: Optional[List[str]] = None,
    ) -> Optional[dict]:
        """
        Calls snmptranslate -Td to extract comprehensive metadata about an object.
        """
        mod_str = ":".join(modules) if modules else "ALL"
        mib_dirs = self.get_mib_dirs_flag(extra_dirs)

        cmd = [self.snmptranslate_exe, "-Td", "-m", mod_str, "-M", mib_dirs, oid_or_name]
        try:
            res = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
                **self._get_silent_kwargs(),
            )
            if res.returncode != 0 or not res.stdout:
                return None
            return self._parse_translate_td(res.stdout)
        except Exception:
            return None

    def _parse_translate_td(self, output: str) -> dict:
        """Parses snmptranslate -Td text output."""
        lines = [line.strip() for line in output.split("\n") if line.strip()]
        data = {
            "symbol": "",
            "oid": "",
            "syntax": "",
            "max_access": "",
            "status": "",
            "description": "",
            "enums": {},
            "raw": output
        }
        if lines:
            data["symbol"] = lines[0]

        import re
        for line in lines:
            if line.startswith("SYNTAX"):
                data["syntax"] = line.replace("SYNTAX", "").strip()
            elif line.startswith("MAX-ACCESS"):
                data["max_access"] = line.replace("MAX-ACCESS", "").strip()
            elif line.startswith("STATUS"):
                data["status"] = line.replace("STATUS", "").strip()
            elif line.startswith("DESCRIPTION"):
                data["description"] = line.replace("DESCRIPTION", "").strip().strip('"')

        # Parse enum values e.g. { enable(1), disable(2) }
        enum_match = re.search(r"\{([^}]+)\}", data["syntax"])
        if enum_match:
            enum_str = enum_match.group(1)
            for pair in enum_str.split(","):
                pm = re.search(r"([A-Za-z0-9_-]+)\s*\((-?\d+)\)", pair.strip())
                if pm:
                    data["enums"][pm.group(1)] = int(pm.group(2))

        return data


process_runner = NetSnmpProcessRunner()
