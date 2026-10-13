import ctypes
from ctypes import wintypes
import os
import re
import sys
from typing import Optional


def sanitize_export_filename(filename: Optional[str], default_prefix: str = "walk_export") -> str:
    """
    Sanitize a filename for Windows/browser saving and ensure it has a .txt extension.
    """
    raw = (filename or "").strip()
    if raw:
        raw = os.path.basename(raw.replace("\\", "/"))
    if not raw:
        raw = f"{default_prefix}.txt"

    # Replace characters invalid in Windows filenames: < > : " / \ | ? * and control chars
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", raw).strip(" .")
    if not sanitized:
        sanitized = f"{default_prefix}.txt"

    if not sanitized.lower().endswith(".txt"):
        sanitized = f"{sanitized}.txt"

    return sanitized


def get_default_initial_dir() -> str:
    """
    Return the user's Downloads folder if it exists, otherwise the user's home directory.
    """
    home = os.path.expanduser("~")
    downloads = os.path.join(home, "Downloads")
    if os.path.isdir(downloads):
        return downloads
    documents = os.path.join(home, "Documents")
    if os.path.isdir(documents):
        return documents
    return home


if sys.platform == "win32":
    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", ctypes.c_void_p),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    OFN_OVERWRITEPROMPT = 0x00000002
    OFN_HIDEREADONLY = 0x00000004
    OFN_NOCHANGEDIR = 0x00000008
    OFN_PATHMUSTEXIST = 0x00000800
    OFN_EXPLORER = 0x00080000
    COINIT_APARTMENTTHREADED = 0x2


def prompt_save_as_dialog(
    default_filename: str,
    initial_dir: Optional[str] = None,
    title: str = "Save Walk Export As",
) -> Optional[str]:
    """
    Open the native Windows Save As dialog so the user can choose where to save the .txt file
    and specify the filename.

    Returns:
        The full user-selected file path as a string, or None if the user cancelled the dialog.
    Raises:
        RuntimeError if the platform does not support the native dialog or if a dialog error occurs.
    """
    if sys.platform != "win32":
        raise RuntimeError("Native Windows Save As dialog is only supported on Windows.")

    safe_name = sanitize_export_filename(default_filename)
    start_dir = initial_dir if (initial_dir and os.path.isdir(initial_dir)) else get_default_initial_dir()

    ole32 = ctypes.windll.ole32
    comdlg32 = ctypes.windll.comdlg32
    user32 = ctypes.windll.user32

    coinit_hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    should_uninit = coinit_hr in (0, 1)  # S_OK (0) or S_FALSE (1)

    try:
        def _invoke_dialog(init_filename: str, init_dir: Optional[str]) -> tuple[bool, str, int]:
            # Double-null-terminated filter string for GetSaveFileNameW
            filter_str = "Text Documents (*.txt)\0*.txt\0All Files (*.*)\0*.*\0\0"
            filter_buf = ctypes.create_unicode_buffer(filter_str, len(filter_str))

            max_path_len = 32768
            file_buf = ctypes.create_unicode_buffer(max_path_len)
            file_buf.value = init_filename

            hwnd_owner = user32.GetForegroundWindow()

            ofn = OPENFILENAMEW()
            ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
            ofn.hwndOwner = hwnd_owner
            ofn.hInstance = None
            ofn.lpstrFilter = ctypes.addressof(filter_buf)
            ofn.lpstrCustomFilter = None
            ofn.nMaxCustFilter = 0
            ofn.nFilterIndex = 1
            ofn.lpstrFile = ctypes.cast(file_buf, wintypes.LPWSTR)
            ofn.nMaxFile = max_path_len
            ofn.lpstrFileTitle = None
            ofn.nMaxFileTitle = 0
            ofn.lpstrInitialDir = init_dir
            ofn.lpstrTitle = title
            ofn.Flags = (
                OFN_EXPLORER
                | OFN_OVERWRITEPROMPT
                | OFN_HIDEREADONLY
                | OFN_PATHMUSTEXIST
                | OFN_NOCHANGEDIR
            )
            ofn.lpstrDefExt = "txt"

            ok = bool(comdlg32.GetSaveFileNameW(ctypes.byref(ofn)))
            if ok:
                return True, file_buf.value.strip(), 0
            err_code = comdlg32.CommDlgExtendedError()
            return False, "", int(err_code)

        ok, chosen_path, err_code = _invoke_dialog(safe_name, start_dir)
        if not ok and err_code != 0:
            # Fallback retry with a simple filename and default OS directory if initial buffer failed
            ok, chosen_path, err_code = _invoke_dialog("walk_export.txt", None)
            if not ok and err_code != 0:
                raise RuntimeError(f"Save As dialog failed with error code 0x{err_code:04X}")

        if not ok or not chosen_path:
            # User clicked Cancel or closed the Save As dialog
            return None

        # Ensure .txt extension if the user omitted an extension
        _, ext = os.path.splitext(chosen_path)
        if not ext:
            chosen_path = f"{chosen_path}.txt"

        return os.path.abspath(chosen_path)
    finally:
        if should_uninit:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass


def save_export_content_to_path(filepath: str, content: str) -> str:
    """
    Write the exported text content to the selected file path and verify it exists on disk.
    """
    if not filepath or not filepath.strip():
        raise ValueError("Target file path cannot be empty.")

    abs_path = os.path.abspath(filepath.strip())
    parent_dir = os.path.dirname(abs_path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    text_to_write = content if content is not None else ""
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(text_to_write)
        f.flush()
        os.fsync(f.fileno())

    if not os.path.isfile(abs_path):
        raise IOError(f"File could not be verified after writing: {abs_path}")

    return abs_path
