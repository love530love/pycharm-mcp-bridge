#!/usr/bin/env python3
"""Configure and diagnose PyCharm's built-in MCP server.

JetBrains ships the MCP server inside PyCharm 2025.2+. This tool is the
integration layer around it: locate PyCharm, write a correct stdio connector
entry into Qoder / WorkBuddy / Cursor style ``mcp.json`` files, and report the
common configuration failures.

Commands:
    detect        Find PyCharm executables
    print-config  Print an mcpServers entry
    install       Merge the entry into a client config (with backup)
    doctor        Check executable, project, process, port and client configs
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

__version__ = "0.2.0"

SERVER_NAME = "pycharm"
DEFAULT_PORT = 64462
CLIENT_CONFIGS = {
    "qoder": Path.home() / ".qoder" / "mcp.json",
    "workbuddy": Path.home() / ".workbuddy" / "mcp.json",
    "cursor": Path.home() / ".cursor" / "mcp.json",
}


class ConflictError(RuntimeError):
    pass


def build_entry(
    pycharm_exe: str | Path,
    project: str | Path,
    port: int = DEFAULT_PORT,
    transport: str = "stdio",
) -> dict:
    if transport == "sse":
        return {"url": f"http://127.0.0.1:{port}/sse"}
    return {
        "command": str(Path(pycharm_exe)),
        "args": ["stdioMcpServer"],
        "env": {
            "IJ_MCP_SERVER_PROJECT_PATH": str(Path(project)),
            "IJ_MCP_SERVER_PORT": str(port),
        },
    }


def load_config(path: Path) -> dict:
    if not path.is_file():
        return {"mcpServers": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"{path}: mcpServers must be an object")
    return data


def merge_entry(config: dict, entry: dict, force: bool = False) -> tuple[dict, str]:
    servers = config.setdefault("mcpServers", {})
    existing = servers.get(SERVER_NAME)
    if existing == entry:
        return config, "unchanged"
    if existing is not None and not force:
        raise ConflictError(
            f"mcpServers.{SERVER_NAME} already exists with different values; re-run with --force to replace it"
        )
    servers[SERVER_NAME] = entry
    return config, "added" if existing is None else "updated"


def install(
    entry: dict,
    config_path: Path,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    config = load_config(config_path)
    config, action = merge_entry(config, entry, force=force)
    result = {"config": str(config_path), "action": action}
    if action == "unchanged" or dry_run:
        result["dry_run"] = dry_run
        result["entry"] = entry
        return result

    backup = None
    if config_path.is_file():
        backup = config_path.with_name(config_path.name + time.strftime(".bak-%Y%m%d-%H%M%S"))
        shutil.copy2(config_path, backup)
        result["backup"] = str(backup)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _candidate_globs() -> list[str]:
    candidates: list[str] = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        program_files = os.environ.get("PROGRAMFILES")
        if local:
            candidates += [
                str(Path(local) / "Programs" / "JetBrains" / "*" / "bin" / "pycharm64.exe"),
                str(Path(local) / "JetBrains" / "Toolbox" / "apps" / "PyCharm*" / "*" / "*" / "bin" / "pycharm64.exe"),
            ]
        if program_files:
            candidates.append(str(Path(program_files) / "JetBrains" / "*" / "bin" / "pycharm64.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/PyCharm*.app/Contents/MacOS/pycharm")
    return candidates


def _configured_paths() -> list[Path]:
    found = []
    for config_path in CLIENT_CONFIGS.values():
        try:
            entry = load_config(config_path).get("mcpServers", {}).get(SERVER_NAME) or {}
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        command = entry.get("command")
        if command and Path(command).is_file():
            found.append(Path(command))
    return found


def detect_pycharm() -> list[Path]:
    from glob import glob

    found: list[Path] = []
    env_exe = os.environ.get("PYCHARM_EXE", "").strip()
    if env_exe and Path(env_exe).is_file():
        found.append(Path(env_exe))

    for name in ("pycharm64.exe", "pycharm.exe", "pycharm", "pycharm.sh"):
        located = shutil.which(name)
        if located:
            found.append(Path(located))

    found += _configured_paths()
    for pattern in _candidate_globs():
        for match in glob(pattern, recursive=True):
            path = Path(match)
            if path.is_file():
                found.append(path)

    unique: dict[str, Path] = {}
    for path in found:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        unique[key] = path
    return sorted(unique.values(), key=lambda item: item.stat().st_mtime, reverse=True)


def port_open(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def runasadmin_flagged(exe: str | Path) -> bool | None:
    if os.name != "nt":
        return None
    import winreg

    target = str(Path(exe).resolve()).lower().replace("/", "\\")
    for root, subkey in (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"),
    ):
        try:
            with winreg.OpenKey(root, subkey) as key:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    if name.lower().replace("/", "\\") == target:
                        return "RUNASADMIN" in str(value).upper()
        except FileNotFoundError:
            continue
        except OSError:
            return None
    return False


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def process_running(image_name: str) -> bool | None:
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        for proc in psutil.process_iter(["name"]):
            if (proc.info.get("name") or "").lower() == image_name.lower():
                return True
        return False
    if os.name != "nt":
        return None
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = _decode(proc.stdout)
    return image_name.lower() in text.lower()


def doctor(
    project: Path | None,
    port: int = DEFAULT_PORT,
    pycharm_exe: Path | None = None,
    config_path: Path | None = None,
) -> dict:
    checks: list[dict] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    candidates = detect_pycharm()
    exe = pycharm_exe or (candidates[0] if candidates else None)
    if exe is None:
        add("pycharm_executable", "error", "PyCharm was not found; pass --pycharm-exe or set PYCHARM_EXE")
    elif not exe.is_file():
        add("pycharm_executable", "error", f"not a file: {exe}")
    else:
        add("pycharm_executable", "ok", str(exe))
        runas = runasadmin_flagged(exe)
        if runas:
            add(
                "runasadmin",
                "warn",
                "this executable is flagged RUNASADMIN; a non-elevated client cannot spawn it via stdio"
                " (WinError 740). Use --transport sse, or launch PyCharm's MCP endpoint directly.",
            )
        elif runas is False:
            add("runasadmin", "ok", "no RUNASADMIN compatibility flag")

    if project is None:
        add("project_path", "warn", "no --project given; set IJ_MCP_SERVER_PROJECT_PATH before installing")
    elif not project.is_dir():
        add("project_path", "error", f"not a directory: {project}")
    elif not (project / ".idea").is_dir():
        add("project_path", "warn", f"no .idea directory at {project}; is this a PyCharm project?")
    else:
        add("project_path", "ok", str(project))

    running = process_running("pycharm64.exe") if os.name == "nt" else process_running("pycharm")
    if running is None:
        add("ide_process", "warn", "process detection unavailable on this platform")
    elif running:
        add("ide_process", "ok", "PyCharm is running")
    else:
        add("ide_process", "warn", "PyCharm is not running; the stdio connector may still start its own server process")

    if port_open("127.0.0.1", port):
        add("sse_port", "ok", f"127.0.0.1:{port} is listening")
    else:
        add(
            "sse_port",
            "warn",
            f"127.0.0.1:{port} is closed; stdio transport does not need it, only SSE does",
        )

    paths = [config_path] if config_path else list(CLIENT_CONFIGS.values())
    for path in paths:
        if not path.is_file():
            if config_path:
                add("client_config", "warn", f"config does not exist: {path}")
            continue
        try:
            entry = load_config(path).get("mcpServers", {}).get(SERVER_NAME)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            add("client_config", "error", f"{path}: {exc}")
            continue
        if entry is None:
            add("client_config", "warn", f"{path}: no {SERVER_NAME} entry")
        elif entry.get("url"):
            parsed = urlparse(entry["url"])
            if parsed.hostname not in ("127.0.0.1", "localhost", "::1") or not parsed.port:
                add("client_config", "warn", f"{path}: unexpected SSE URL: {entry['url']}")
            elif port_open(parsed.hostname, parsed.port):
                add("client_config", "ok", str(path))
            else:
                add(
                    "client_config",
                    "warn",
                    f"{path}: {entry['url']} is not listening; open the project in PyCharm and enable"
                    " Settings -> Tools -> MCP Server",
                )
        else:
            command = entry.get("command")
            if command and not Path(command).is_file():
                add("client_config", "warn", f"{path}: command not found: {command}")
            elif command and runasadmin_flagged(command):
                add(
                    "client_config",
                    "error",
                    f"{path}: stdio entry spawns {command}, which is RUNASADMIN-flagged; non-elevated"
                    " clients fail with WinError 740. Reinstall with --transport sse.",
                )
            else:
                add("client_config", "ok", str(path))

    has_error = any(item["status"] == "error" for item in checks)
    return {"ok": not has_error, "checks": checks}


def _resolve_exe(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser()
    candidates = detect_pycharm()
    if not candidates:
        raise SystemExit("PyCharm was not found; pass --pycharm-exe or set PYCHARM_EXE")
    return candidates[0]


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pycharm-mcp-bridge",
        description="Configure and diagnose PyCharm's built-in MCP server.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("detect", help="Find installed PyCharm executables")

    print_config = subparsers.add_parser("print-config", help="Print an mcpServers entry")
    print_config.add_argument("--project", required=True, help="PyCharm project path")
    print_config.add_argument("--port", type=int, default=DEFAULT_PORT)
    print_config.add_argument("--pycharm-exe", help="PyCharm executable path")
    print_config.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="stdio spawns the IDE executable; sse connects to the IDE web server (recommended when the exe is RUNASADMIN-flagged)",
    )

    installer = subparsers.add_parser("install", help="Merge the entry into a client config")
    installer.add_argument("--client", choices=[*CLIENT_CONFIGS, "all"], required=True)
    installer.add_argument("--project", required=True, help="PyCharm project path")
    installer.add_argument("--port", type=int, default=DEFAULT_PORT)
    installer.add_argument("--pycharm-exe", help="PyCharm executable path")
    installer.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="stdio spawns the IDE executable; sse connects to the IDE web server",
    )
    installer.add_argument("--config", help="Explicit mcp.json path (overrides --client target)")
    installer.add_argument("--force", action="store_true", help="Replace an existing entry")
    installer.add_argument("--dry-run", action="store_true", help="Show the result without writing")

    checker = subparsers.add_parser("doctor", help="Check the connector setup")
    checker.add_argument("--project", help="PyCharm project path")
    checker.add_argument("--port", type=int, default=DEFAULT_PORT)
    checker.add_argument("--pycharm-exe", help="PyCharm executable path")
    checker.add_argument("--config", help="Check only this mcp.json path")

    args = parser.parse_args(argv)

    if args.command == "detect":
        _print_json({"executables": [str(path) for path in detect_pycharm()]})
        return 0

    if args.command == "print-config":
        exe = _resolve_exe(args.pycharm_exe) if args.transport == "stdio" else args.pycharm_exe or ""
        entry = build_entry(exe, args.project, args.port, args.transport)
        _print_json({"mcpServers": {SERVER_NAME: entry}})
        return 0

    if args.command == "install":
        exe = _resolve_exe(args.pycharm_exe) if args.transport == "stdio" else args.pycharm_exe or ""
        entry = build_entry(exe, args.project, args.port, args.transport)
        clients = list(CLIENT_CONFIGS) if args.client == "all" else [args.client]
        results = []
        for client in clients:
            config_path = Path(args.config).expanduser() if args.config else CLIENT_CONFIGS[client]
            results.append(install(entry, config_path, force=args.force, dry_run=args.dry_run))
        _print_json({"results": results})
        return 0

    report = doctor(
        Path(args.project).expanduser() if args.project else None,
        port=args.port,
        pycharm_exe=Path(args.pycharm_exe).expanduser() if args.pycharm_exe else None,
        config_path=Path(args.config).expanduser() if args.config else None,
    )
    for item in report["checks"]:
        print(f"[{item['status']:5}] {item['check']}: {item['detail']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
