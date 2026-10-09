#!/usr/bin/env python3
"""Builds a self-contained bundle for the offline GPU server (Ubuntu 20.04, x86_64, Python 3.10).

Run on a machine with internet access, from the repository root:

    python deploy/build_offline_bundle.py                 # -> dist/ppe-platform-<sha>-offline.tar.gz

The bundle holds everything the server can't download itself:
    src/         application source (tracked files; never model weights, which stay on the server)
    wheelhouse/  Linux/CPython 3.10 wheels for backend/requirements.lock (+ pip)
    web/         Next.js standalone server (node web/server.js), static assets included
    node/        Node.js LTS for linux-x64
    install.sh   copies it all into place on the server (see docs/DEPLOYMENT.md)

Standard library only, so any Python 3.10+ can run it.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY_VERSION = "3.10"
# The server's glibc is 2.31 (Ubuntu 20.04); older manylinux tags are compatible too
PLATFORMS = ["manylinux_2_31_x86_64", "manylinux_2_28_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64"]
# Never shipped: secrets, local data, build output, and the LFS-tracked model weights
EXCLUDE_PREFIXES = ("model/", "var/", "dist/", "training/", ".env")


def run(cmd, cwd=REPO, env=None):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, check=True, shell=os.name == "nt" and cmd[0] in ("npm", "npx"))


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout


def copy_source(dest: Path) -> str:
    files = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    copied = 0
    for rel in filter(None, files):
        if rel.startswith(EXCLUDE_PREFIXES) or "/node_modules/" in rel or rel.startswith("frontend/.next"):
            continue
        src = REPO / rel
        if not src.is_file():
            continue  # deleted in the working tree
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied += 1
    sha = git("rev-parse", "--short", "HEAD").strip()
    dirty = bool(git("status", "--porcelain").strip())
    (dest / "BUNDLE_VERSION").write_text(f"{sha}{'-dirty' if dirty else ''}\n", encoding="utf-8")
    print(f"Copied {copied} source files ({sha}{', uncommitted changes included' if dirty else ''})")
    return sha + ("-dirty" if dirty else "")


def download_wheels(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    common = [
        sys.executable, "-m", "pip", "download", "--dest", dest, "--only-binary=:all:",
        "--python-version", PY_VERSION, "--implementation", "cp",
        "--abi", "cp310", "--abi", "abi3", "--abi", "none",
    ]
    for p in PLATFORMS:
        common += ["--platform", p]
    run([*common, "-r", REPO / "backend" / "requirements.lock"])
    # pip itself, for servers where `python3.10 -m venv` lacks ensurepip (python3.10-venv not installed)
    run([*common, "pip"])
    print(f"{len(list(dest.glob('*.whl')))} wheels in {dest}")


def build_web(dest: Path, api_origin: str, npm_ci: bool) -> None:
    frontend = REPO / "frontend"
    if npm_ci or not (frontend / "node_modules").is_dir():
        run(["npm", "ci"], cwd=frontend)
    shutil.rmtree(frontend / ".next", ignore_errors=True)
    env = {**os.environ, "API_ORIGIN": api_origin, "NEXT_TELEMETRY_DISABLED": "1"}
    run(["npx", "next", "build"], cwd=frontend, env=env)

    standalone = frontend / ".next" / "standalone"
    shutil.copytree(standalone, dest, symlinks=False)
    shutil.copytree(frontend / ".next" / "static", dest / ".next" / "static")
    shutil.copytree(frontend / "public", dest / "public")
    native = [p for p in dest.rglob("*.node")]
    links = [p for p in dest.rglob("*") if p.is_symlink()]
    if native or links:
        raise SystemExit(f"Standalone output isn't portable: native modules {native[:3]}, links {links[:3]}")
    print(f"Web build ready in {dest}")


def download_node(dest_dir: Path, major: str) -> Path:
    with urllib.request.urlopen("https://nodejs.org/dist/index.json", timeout=60) as r:
        releases = json.load(r)
    release = next(x for x in releases if x["version"].startswith(f"v{major}.") and x["lts"])
    version = release["version"]
    name = f"node-{version}-linux-x64.tar.xz"
    base = f"https://nodejs.org/dist/{version}/"
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / name
    print(f"Downloading {name}")
    urllib.request.urlretrieve(base + name, target)
    with urllib.request.urlopen(base + "SHASUMS256.txt", timeout=60) as r:
        sums = dict(line.split()[::-1] for line in r.read().decode().splitlines() if line.strip())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if sums.get(name) != digest:
        raise SystemExit(f"Checksum mismatch for {name}")
    print(f"Node {version} verified")
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="dist", help="output directory (default: dist/)")
    ap.add_argument("--api-origin", default="http://127.0.0.1:8001", help="where the web server proxies /api")
    ap.add_argument("--node-major", default="22", help="Node.js LTS major version (default: 22)")
    ap.add_argument("--npm-ci", action="store_true", help="reinstall frontend dependencies first")
    ap.add_argument("--skip-web", action="store_true")
    ap.add_argument("--skip-wheels", action="store_true")
    ap.add_argument("--skip-node", action="store_true")
    args = ap.parse_args()

    out = (REPO / args.out).resolve()
    staging = out / "ppe-platform-offline"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    version = copy_source(staging / "src")
    if not args.skip_wheels:
        download_wheels(staging / "wheelhouse")
    if not args.skip_web:
        build_web(staging / "web", args.api_origin, args.npm_ci)
    if not args.skip_node:
        download_node(staging / "node", args.node_major)
    shutil.copy2(REPO / "deploy" / "install_offline.sh", staging / "install.sh")

    archive = out / f"ppe-platform-{version}-offline.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staging, arcname="ppe-platform-offline")
    print(f"\nBundle: {archive} ({archive.stat().st_size / 1e6:.0f} MB)")
    print("Copy it to the server, then: tar -xzf <bundle> && sudo -u administrator bash ppe-platform-offline/install.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
