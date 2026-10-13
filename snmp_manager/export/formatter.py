from snmp.walk import WalkSession
from datetime import datetime


def format_walk_export(
    device: dict,
    session: WalkSession,
    oid_from: str,
    oid_to: str = None,
) -> str:
    lines = []

    version_map = {"v1": "SNMPv1", "v2c": "SNMPv2c", "v3": "SNMPv3"}
    version_str = version_map.get(device.get("version", "v2c"), device.get("version", "v2c"))

    oid_from_display = oid_from
    oid_to_display = oid_to or oid_from

    target_label = device.get("name") or oid_from_display
    lines.append(f"Walk: {target_label} to {oid_to_display}, 7 - {device.get('ip_address', '')}:{device.get('port', 161)}- {version_str}")
    lines.append("")

    lines.append("[SNMP Agent]")
    lines.append(f"IP Address = {device.get('ip_address', '')}")
    lines.append(f"Port = {device.get('port', 161)}")
    lines.append(f"Name = {device.get('name', '')}")
    lines.append(f"ReadCommunity = {device.get('read_community', '')}")
    lines.append(f"WriteCommunity = {device.get('write_community', '')}")
    lines.append(f"NumRetries = {device.get('retries', 2)}")
    lines.append(f"TimeOut = {device.get('timeout', 2)}")
    lines.append(f"Version = {version_str}")
    lines.append("")

    lines.append("[Query Parameters]")
    lines.append("Type = Walk (6)")
    lines.append(f"From = {oid_from}")
    lines.append(f"To = {oid_to_display}")
    started = session.started_at
    if isinstance(started, datetime):
        started_str = started.strftime("%d-%m-%Y %H:%M:%S")
    else:
        started_str = str(started)
    lines.append(f"Start Time = {started_str}")
    lines.append("")

    lines.append("[Query Results]")
    completed = session.completed_at
    if completed is None:
        completed = datetime.now()
    if isinstance(completed, datetime):
        completed_str = completed.strftime("%d-%m-%Y %H:%M:%S")
    else:
        completed_str = str(completed)
    lines.append(f"Response Time = {completed_str}")
    status_map = {
        "completed": "End of Walk",
        "stopped": "Stopped by User",
        "running": "In Progress",
    }
    if session.status == "error":
        status_map["error"] = f"Error: {session.error}"
    lines.append(f"Response Status = {status_map.get(session.status, session.status)}")
    lines.append("")

    # Preserve exact walk order without separating or moving failed OIDs to the bottom
    sorted_results = sorted(session.results, key=lambda x: getattr(x, "seq", 0)) if session.results else []
    for vb in sorted_results:
        name_part = vb.name
        if vb.index:
            name_part = f"{vb.name}.{vb.index}"
        if getattr(vb, "status", "ok") == "ok":
            disp_type = getattr(vb, "display_type", None) or vb.type
            disp_val = getattr(vb, "display_value", None)
            if disp_val is None:
                disp_val = vb.value
            if disp_val == "":
                disp_val = '""'
            lines.append(f"{name_part} ({disp_type}) = {disp_val}")
        else:
            reason = vb.error_msg or vb.value or "No response from agent"
            lines.append(f"{name_part} (FAILED) = {reason}")

    return "\n".join(lines)