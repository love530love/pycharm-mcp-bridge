# pycharm-mcp-bridge

Configuration and diagnostics for PyCharm's built-in MCP server.

PyCharm 2025.2+ ships an MCP server inside the IDE (`pycharm64.exe stdioMcpServer`). That server is proprietary and closed-source; this project is the open integration layer around it:

- find the PyCharm executable
- write a correct stdio connector entry into Qoder / WorkBuddy / Cursor style `mcp.json`
- back up existing configs and merge without touching other servers
- diagnose the usual failures: missing executable, wrong project path, closed SSE port, broken client entries

## What this project is not

It does not contain, modify or redistribute JetBrains code. It does not replace the IDE MCP server. It only automates the setup that you would otherwise do by hand.

## Requirements

- PyCharm 2025.2 or newer
- MCP Server enabled in **Settings -> Tools -> MCP Server**
- "Run shell commands without confirmation" (Brave mode) is strongly recommended for agent workflows
- Python 3.10+ for this CLI

## Quick start

```bash
# 1. find PyCharm
python pycharm_mcp_bridge.py detect

# 2. preview the entry
python pycharm_mcp_bridge.py print-config --project H:/PythonProjects3/Win_ComfyUI

# 3. install into Qoder (writes ~/.qoder/mcp.json, backs up the old file)
python pycharm_mcp_bridge.py install --client qoder --project H:/PythonProjects3/Win_ComfyUI

# 4. verify
python pycharm_mcp_bridge.py doctor --project H:/PythonProjects3/Win_ComfyUI
```

Targets: `--client qoder|workbuddy|cursor|all`, or `--config <path>` for any other `mcp.json`.

### Generated entry

```json
{
  "mcpServers": {
    "pycharm": {
      "command": "D:/Program/JetBrains/PyCharm/bin/pycharm64.exe",
      "args": ["stdioMcpServer"],
      "env": {
        "IJ_MCP_SERVER_PROJECT_PATH": "H:/PythonProjects3/Win_ComfyUI",
        "IJ_MCP_SERVER_PORT": "64462"
      }
    }
  }
}
```

## Commands

| Command | Purpose |
| --- | --- |
| `detect` | List detected PyCharm executables (env, PATH, Toolbox, existing client configs) |
| `print-config` | Print a ready-to-paste `mcpServers` entry |
| `install` | Merge the entry into one or more client configs; `--force` replaces conflicts; `--dry-run` previews |
| `doctor` | Check executable, project, IDE process, SSE port and client configs |

`doctor` exits with code 1 when it finds an error, so it can run in scripts.

## Known pitfalls

1. **The IDE terminal server does not inherit your virtual environment.** Commands launched through PyCharm MCP start a fresh shell. Call the project interpreter by absolute path (`C:/project/.venv/Scripts/python.exe`) instead of `python`.
2. **stdio is more reliable than SSE.** Some clients cannot reach loopback SSE endpoints from their sandbox. The generated entry uses stdio; the `IJ_MCP_SERVER_PORT` value is only used by the IDE side.
3. **Windows console encoding.** Set `PYTHONUTF8=1` in the environment you manage, especially when custom nodes print non-ASCII text.
4. **PyCharm must stay installed.** The stdio connector launches the IDE executable; closing the IDE window is fine, uninstalling it is not.

## Development

```bash
pip install -r requirements-dev.txt
pytest -q
```

## 中文说明

PyCharm 2025.2+ 内置了 MCP Server（闭源），本项目是它的开源集成层：

- `detect` 自动定位 PyCharm（环境变量 `PYCHARM_EXE`、PATH、JetBrains Toolbox、已有客户端配置）
- `install --client qoder|workbuddy|cursor|all` 自动合并 `mcp.json`，写前备份，不碰其他服务器
- `doctor` 检查可执行文件、项目路径、IDE 进程、SSE 端口、客户端配置

常见坑：MCP 终端不继承 venv（用解释器绝对路径）；沙箱客户端访问不了 loopback SSE（用 stdio）；Windows 下建议 `PYTHONUTF8=1`。

## License

MIT
