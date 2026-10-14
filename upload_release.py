import subprocess
import urllib.request
import json
import os
import sys

def main():
    print("Retrieving GitHub credentials...")
    proc = subprocess.Popen(
        ['git', 'credential', 'fill'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    stdout, _ = proc.communicate("protocol=https\nhost=github.com\n")
    token = None
    for line in stdout.splitlines():
        if line.startswith("password="):
            token = line.split("=", 1)[1].strip()

    if not token:
        print("ERROR: Could not retrieve GitHub token from Git Credential Manager.")
        sys.exit(1)

    repo = "Bhagyarajbheesetty/net-snmp-visual-manager"
    tag = "v1.0.0"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "NetSNMP-Release-Publisher"
    }

    # 1. Check if release already exists
    check_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    req = urllib.request.Request(check_url, headers=headers)
    release = None
    try:
        with urllib.request.urlopen(req) as resp:
            release = json.loads(resp.read().decode())
            print(f"Release {tag} already exists: {release.get('html_url')}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"Release {tag} does not exist yet. Creating...")
        else:
            print(f"Error checking release: {e}")
            sys.exit(1)

    release_notes = (
        "## SNMP Visual Manager v1.0.0\n\n"
        "A modern, standalone Windows desktop application and web GUI for **Net-SNMP 5.9.5.2**.\n\n"
        "### Downloads\n"
        "- **`NetSNMPManager_Setup_v1.0.exe`**: Complete 64-bit Windows setup wizard with bundled Net-SNMP 5.9.5.2 tools and standard MIBs.\n\n"
        "### Features & Highlights\n"
        "- **SNMPv1 / SNMPv2c / SNMPv3 USM Support**: MD5, SHA, SHA256, DES, AES with quick connection tests.\n"
        "- **Visual MIB Tree & Browser**: Explore 65+ bundled MIBs and easily load external vendor MIBs.\n"
        "- **Advanced SET Options & Template C Guidance**: Live integer enum hints, interactive quick-fill pills, GET read status codes, and timing alert callouts.\n"
        "- **Smart Table Column Resolution**: Automatically resolves first row instance (e.g. .1.1) when GET is run on columnar OIDs instead of returning 'No Such Instance'.\n"
        "- **Live Walk & BulkWalk Operations**: Fast, adaptive walk with gap detection and strict OID sequencing.\n"
        "- **Native Windows Save As Dialog**: Reliable export directly to your chosen folder.\n"
        "- **Clean Data Architecture**: Strict separation between `register.json` and `snmp_manager.db`.\n\n"
        "### Authors & Contributors\n"
        "- **Bhagyaraj Bheesetty** - Application Author & Maintainer\n"
        "- **Antigravity (Google DeepMind)** - AI Assistant & Contributor\n\n"
        "### Credits & Legal Attribution\n"
        "- **Net-SNMP 5.9.5.2**: [http://www.net-snmp.org/](http://www.net-snmp.org/) (Email: `net-snmp-coders@lists.sourceforge.net`)\n"
        "- All rights, copyrights, and trademarks are reserved by the original authors and contributors of the Net-SNMP project.\n"
        "- Licensed under the **MIT License**. Free open-source software for all users.\n"
    )

    # 2. Create release if not exists, or update description if exists
    if not release:
        create_url = f"https://api.github.com/repos/{repo}/releases"
        body = {
            "tag_name": tag,
            "target_commitish": "main",
            "name": "SNMP Visual Manager v1.0.0",
            "body": release_notes,
            "draft": False,
            "prerelease": False
        }
        data = json.dumps(body).encode("utf-8")
        post_req = urllib.request.Request(create_url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(post_req) as resp:
            release = json.loads(resp.read().decode())
            print(f"Successfully created release: {release.get('html_url')}")
    else:
        patch_url = release["url"]
        patch_body = {"body": release_notes}
        patch_req = urllib.request.Request(patch_url, data=json.dumps(patch_body).encode("utf-8"), headers=headers, method="PATCH")
        with urllib.request.urlopen(patch_req) as resp:
            release = json.loads(resp.read().decode())
            print(f"Updated release notes with latest contributor attributions on GitHub.")

    # 3. Upload Setup Executable
    asset_path = os.path.join(os.path.dirname(__file__), "dist_installer", "NetSNMPManager_Setup_v1.0.exe")
    if not os.path.isfile(asset_path):
        print(f"ERROR: Asset file not found at {asset_path}")
        sys.exit(1)

    asset_name = "NetSNMPManager_Setup_v1.0.exe"
    asset_size = os.path.getsize(asset_path)

    # Check if identical asset already exists in release
    existing_matching = [a for a in release.get("assets", []) if a.get("name") == asset_name and a.get("size") == asset_size]
    if existing_matching:
        print(f"\nAsset '{asset_name}' is already attached to release ({asset_size:,} bytes). Skipping redundant upload.")
        print(f"Release URL: {release.get('html_url')}")
        return

    # If asset with same name already exists in release but different size, delete it first
    for a in release.get("assets", []):
        if a.get("name") == asset_name:
            print(f"Deleting existing asset '{asset_name}' (ID: {a['id']})...")
            del_req = urllib.request.Request(a["url"], headers=headers, method="DELETE")
            urllib.request.urlopen(del_req)

    print(f"Uploading {asset_name} ({asset_size:,} bytes) to GitHub Release...")
    upload_url_base = release["upload_url"].split("{")[0]
    upload_url = f"{upload_url_base}?name={asset_name}"

    with open(asset_path, "rb") as f:
        file_bytes = f.read()

    upload_headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/octet-stream",
        "User-Agent": "NetSNMP-Release-Publisher",
        "Content-Length": str(len(file_bytes))
    }

    upload_req = urllib.request.Request(upload_url, data=file_bytes, headers=upload_headers, method="POST")
    with urllib.request.urlopen(upload_req) as resp:
        uploaded_asset = json.loads(resp.read().decode())
        print("\n========================================================")
        print("RELEASE ASSET UPLOADED SUCCESSFULLY!")
        print("========================================================")
        print(f"Release URL:        {release.get('html_url')}")
        print(f"Asset Name:         {uploaded_asset.get('name')}")
        print(f"Size:               {uploaded_asset.get('size'):,} bytes")
        print(f"Direct Download:    {uploaded_asset.get('browser_download_url')}")
        print("========================================================\n")

if __name__ == "__main__":
    main()
