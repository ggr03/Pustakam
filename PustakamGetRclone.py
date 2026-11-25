"""
Pustakam (पुस्तकम्) — fetch the official rclone build (used for OneDrive sign-in/sync).

Downloads the current release for this OS/CPU from https://downloads.rclone.org,
checks it against the release's SHA256SUMS, and puts the single rclone binary in
the given folder. No root/admin rights needed.

    python PustakamGetRclone.py <dest_dir>
"""
import hashlib
import io
import os
import platform
import re
import stat
import sys
import urllib.request
import zipfile

BASE = "https://downloads.rclone.org"
UA = {"User-Agent": "Pustakam-installer"}


def _get(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _target():
    osname = {"linux": "linux", "win32": "windows", "darwin": "osx"}.get(sys.platform)
    m = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64",
            "armv7l": "arm-v7", "armv6l": "arm", "i386": "386", "i686": "386", "x86": "386"}.get(m)
    if not osname or not arch:
        raise SystemExit(f"No official rclone build for {sys.platform}/{m}; install rclone yourself.")
    return osname, arch


def main(dest):
    osname, arch = _target()
    version = _get(f"{BASE}/version.txt", 30).decode().strip().split()[-1]   # e.g. v1.69.1
    name = f"rclone-{version}-{osname}-{arch}.zip"
    print(f"Downloading {name} from {BASE}/{version}/ ...", flush=True)
    sums = _get(f"{BASE}/{version}/SHA256SUMS", 30).decode()
    m = re.search(rf"^([0-9a-f]{{64}})\s+\*?{re.escape(name)}\s*$", sums, re.M)
    if not m:
        raise SystemExit("Checksum for this build not found in SHA256SUMS; aborting.")
    data = _get(f"{BASE}/{version}/{name}", 600)
    if hashlib.sha256(data).hexdigest() != m.group(1):
        raise SystemExit("Checksum mismatch; the download is damaged or was tampered with. Aborting.")
    exe = "rclone.exe" if osname == "windows" else "rclone"
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        member = next(n for n in z.namelist() if n.endswith("/" + exe))
        out = os.path.join(dest, exe)
        tmp = out + ".tmp"
        with open(tmp, "wb") as f:
            f.write(z.read(member))
        os.chmod(tmp, os.stat(tmp).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(tmp, out)
    print(f"rclone {version} installed: {out} (sha256 verified)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
