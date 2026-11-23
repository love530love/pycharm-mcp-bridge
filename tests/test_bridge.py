import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pycharm_mcp_bridge as bridge


def test_build_entry():
    entry = bridge.build_entry("C:/PyCharm/bin/pycharm64.exe", "H:/project", 64462)
    assert entry["command"].replace("\\", "/").endswith("C:/PyCharm/bin/pycharm64.exe")
    assert entry["args"] == ["stdioMcpServer"]
    assert entry["env"]["IJ_MCP_SERVER_PROJECT_PATH"].replace("\\", "/") == "H:/project"
    assert entry["env"]["IJ_MCP_SERVER_PORT"] == "64462"


def test_build_entry_sse():
    entry = bridge.build_entry("C:/PyCharm/bin/pycharm64.exe", "H:/project", 64462, transport="sse")
    assert entry == {"url": "http://127.0.0.1:64462/sse"}


def test_doctor_flags_runasadmin_stdio_entry(tmp_path, monkeypatch):
    exe = tmp_path / "pycharm64.exe"
    exe.write_text("", encoding="utf-8")
    project = tmp_path / "project"
    (project / ".idea").mkdir(parents=True)
    config_path = tmp_path / "mcp.json"
    entry = bridge.build_entry(exe, project, port=1)
    config_path.write_text(json.dumps({"mcpServers": {"pycharm": entry}}), encoding="utf-8")
    monkeypatch.setattr(bridge, "runasadmin_flagged", lambda path: True)

    report = bridge.doctor(project, port=1, pycharm_exe=exe, config_path=config_path)
    statuses = {item["check"]: item["status"] for item in report["checks"]}
    assert report["ok"] is False
    assert statuses["runasadmin"] == "warn"
    assert statuses["client_config"] == "error"


def test_doctor_warns_closed_sse_endpoint(tmp_path, monkeypatch):
    exe = tmp_path / "pycharm64.exe"
    exe.write_text("", encoding="utf-8")
    project = tmp_path / "project"
    (project / ".idea").mkdir(parents=True)
    config_path = tmp_path / "mcp.json"
    entry = bridge.build_entry("ignored", project, port=1, transport="sse")
    config_path.write_text(json.dumps({"mcpServers": {"pycharm": entry}}), encoding="utf-8")
    monkeypatch.setattr(bridge, "runasadmin_flagged", lambda path: False)

    report = bridge.doctor(project, port=1, pycharm_exe=exe, config_path=config_path)
    statuses = {item["check"]: item["status"] for item in report["checks"]}
    assert report["ok"] is True
    assert statuses["client_config"] == "warn"


def test_merge_entry_add_unchanged_and_conflict():
    entry = bridge.build_entry("C:/PyCharm/pycharm64.exe", "H:/project")
    config, action = bridge.merge_entry({"mcpServers": {}}, entry)
    assert action == "added"
    assert config["mcpServers"]["pycharm"] == entry

    config, action = bridge.merge_entry(config, entry)
    assert action == "unchanged"

    other = bridge.build_entry("D:/Other/pycharm64.exe", "H:/project")
    try:
        bridge.merge_entry(config, other)
    except bridge.ConflictError:
        pass
    else:
        raise AssertionError("expected ConflictError")

    config, action = bridge.merge_entry(config, other, force=True)
    assert action == "updated"
    assert config["mcpServers"]["pycharm"]["command"] == other["command"]


def test_install_preserves_other_servers_and_creates_backup(tmp_path):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps({"mcpServers": {"keep": {"url": "http://localhost"}}}),
        encoding="utf-8",
    )
    entry = bridge.build_entry(sys.executable, tmp_path)
    result = bridge.install(entry, config_path)
    assert result["action"] == "added"
    assert Path(result["backup"]).is_file()

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["mcpServers"]["keep"] == {"url": "http://localhost"}
    assert saved["mcpServers"]["pycharm"] == entry


def test_install_dry_run_does_not_write(tmp_path):
    config_path = tmp_path / "mcp.json"
    entry = bridge.build_entry(sys.executable, tmp_path)
    result = bridge.install(entry, config_path, dry_run=True)
    assert result["dry_run"] is True
    assert not config_path.exists()


def test_doctor_reports_ok_for_valid_setup(tmp_path):
    exe = tmp_path / "pycharm64.exe"
    exe.write_text("", encoding="utf-8")
    project = tmp_path / "project"
    (project / ".idea").mkdir(parents=True)
    config_path = tmp_path / "mcp.json"
    entry = bridge.build_entry(exe, project, port=1)
    config_path.write_text(json.dumps({"mcpServers": {"pycharm": entry}}), encoding="utf-8")

    report = bridge.doctor(project, port=1, pycharm_exe=exe, config_path=config_path)
    statuses = {item["check"]: item["status"] for item in report["checks"]}
    assert report["ok"] is True
    assert statuses["pycharm_executable"] == "ok"
    assert statuses["project_path"] == "ok"
    assert statuses["client_config"] == "ok"


def test_doctor_flags_missing_project(tmp_path):
    exe = tmp_path / "pycharm64.exe"
    exe.write_text("", encoding="utf-8")
    report = bridge.doctor(tmp_path / "missing", port=1, pycharm_exe=exe, config_path=tmp_path / "none.json")
    assert report["ok"] is False
    statuses = {item["check"]: item["status"] for item in report["checks"]}
    assert statuses["project_path"] == "error"
