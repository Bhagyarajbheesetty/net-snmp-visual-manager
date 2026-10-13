import sys
import os
import threading
import socket
import time
import traceback
import urllib.request
from pathlib import Path

# Ensure root paths resolve properly inside PyInstaller frozen bundle or dev
if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
else:
    BASE_DIR = Path(__file__).resolve().parent

# Ensure both BASE_DIR and snmp_manager are in sys.path
for p in [str(BASE_DIR), str(BASE_DIR / "snmp_manager")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import uvicorn

# Patch pywebview's interop_dll_path to ensure PyInstaller onedir bundle locates native WebView2 runtimes
try:
    import webview.util
    _orig_interop_dll_path = webview.util.interop_dll_path

    def _patched_interop_dll_path(dll_name: str) -> str:
        try:
            return _orig_interop_dll_path(dll_name)
        except FileNotFoundError:
            base_dirs = []
            if getattr(sys, "frozen", False):
                exe_dir = os.path.dirname(sys.executable)
                meipass = getattr(sys, "_MEIPASS", "")
                base_dirs.extend([
                    exe_dir,
                    os.path.join(exe_dir, "_internal"),
                    meipass,
                    os.path.join(meipass, "_internal") if meipass else "",
                ])
            base_dirs.extend([
                str(BASE_DIR),
                os.path.join(str(BASE_DIR), "_internal"),
                os.path.dirname(os.path.realpath(__file__)),
            ])
            for base in base_dirs:
                if not base:
                    continue
                candidates = [
                    os.path.join(base, "webview", "lib", "runtimes", dll_name, "native"),
                    os.path.join(base, "webview", "lib", "runtimes", dll_name),
                    os.path.join(base, "webview", "lib", dll_name),
                    os.path.join(base, "lib", "runtimes", dll_name, "native"),
                    os.path.join(base, "lib", dll_name),
                    os.path.join(base, dll_name),
                ]
                for cand in candidates:
                    if os.path.exists(cand):
                        return cand

            # If an architecture runtime directory like win-arm64 or win-x86 is missing on an x64 system,
            # fallback to win-x64 runtime or empty directory so edgechromium.py does not crash.
            if dll_name in ("win-arm64", "win-x86"):
                for base in base_dirs:
                    if not base:
                        continue
                    cand = os.path.join(base, "webview", "lib", "runtimes", "win-x64", "native")
                    if os.path.exists(cand):
                        return cand
                return ""
            raise

    webview.util.interop_dll_path = _patched_interop_dll_path
except Exception as _patch_err:
    pass

import webview

LOG_FILE = os.path.expanduser("~/.snmp-manager/desktop_app.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def log(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def find_free_port(start_port=28080):
    """
    Find a guaranteed open port on loopback without colliding with common web/proxy ports like 8080.
    Uses OS dynamic port allocation or a dedicated high range (28080+).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            if port > 1024:
                return port
    except Exception:
        pass

    # Search dedicated high-range fallback
    for port in range(start_port, start_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return 28080

server_instance = None
server_error = None

def start_server(port):
    """Runs FastAPI via Uvicorn in a background thread."""
    global server_instance, server_error
    try:
        log(f"Starting embedded FastAPI server on 127.0.0.1:{port}...")
        from main import app
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server_instance = uvicorn.Server(config)
        server_instance.run()
    except Exception as e:
        server_error = f"{e}\n{traceback.format_exc()}"
        log(f"Server startup exception:\n{server_error}")

def wait_for_server(port, timeout=15):
    """Wait until loopback HTTP health check responds."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as resp:
                if resp.status == 200:
                    log(f"Server is healthy and responding on 127.0.0.1:{port}")
                    return True
        except Exception:
            pass
        time.sleep(0.15)
    return False

def on_closing():
    """Trigger graceful server shutdown when window closes."""
    global server_instance
    log("Desktop window closing, stopping background server...")
    if server_instance:
        server_instance.should_exit = True

def main():
    log("--- SNMP Visual Manager Starting ---")
    port = find_free_port()
    log(f"Selected port: {port}")
    
    # Launch uvicorn daemon thread
    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()

    # Wait for server readiness
    is_ready = wait_for_server(port)
    if not is_ready:
        err_msg = server_error or "Embedded server did not respond to health check within timeout."
        log(f"Error: {err_msg}")

    # Create native WebView2 desktop window
    window = webview.create_window(
        title="SNMP Visual Manager",
        url=f"http://127.0.0.1:{port}",
        width=1280,
        height=850,
        min_size=(1024, 680),
        text_select=True,
        confirm_close=False
    )
    window.events.closing += on_closing
    
    # Start webview event loop (blocks until window is closed)
    try:
        webview.start(gui="edgechromium", debug=False)
    except Exception as e:
        log(f"WebView initialization failed: {e}. Falling back to default browser.")
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{port}")
        # Keep process alive while user interacts via browser
        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            pass
    sys.exit(0)

if __name__ == "__main__":
    main()
