# pycharm-mcp-bridge

Configuration and diagnostics for PyCharm's built-in MCP server.

PyCharm 2025.2+ ships an MCP server inside the IDE (`pycharm64.exe stdioMcpServer`). That server is proprietary and closed-source; this project is the open integration layer around it:

- find the PyCharm executable
- write a correct stdio or SSE connector entry into Qoder / WorkBuddy / Cursor style `mcp.json`
- back up existing configs and merge without touching other servers
- diagnose the usual failures: missing executable, wrong project path, closed SSE port, broken client entries, `RUNASADMIN`-flagged executables that break stdio launch

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

If `doctor` reports a `RUNASADMIN` warning, skip stdio and use the SSE endpoint instead:

```bash
python pycharm_mcp_bridge.py install --client qoder --transport sse --project H:/PythonProjects3/Win_ComfyUI
```

### Generated entries

stdio (default) — spawns the IDE executable:

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

SSE (`--transport sse`) — connects to the IDE's built-in web server; the IDE must be open on the project:

```json
{
  "mcpServers": {
    "pycharm": { "url": "http://127.0.0.1:64462/sse" }
  }
}
```

## Commands

| Command | Purpose |
| --- | --- |
| `detect` | List detected PyCharm executables (env, PATH, Toolbox, existing client configs) |
| `print-config` | Print a ready-to-paste `mcpServers` entry (`--transport stdio|sse`) |
| `install` | Merge the entry into one or more client configs; `--force` replaces conflicts; `--dry-run` previews; `--transport stdio|sse` |
| `doctor` | Check executable, project, IDE process, SSE port, `RUNASADMIN` flag and client configs |

`doctor` exits with code 1 when it finds an error, so it can run in scripts.

## Known pitfalls

1. **The IDE terminal server does not inherit your virtual environment.** Commands launched through PyCharm MCP start a fresh shell. Call the project interpreter by absolute path (`C:/project/.venv/Scripts/python.exe`) instead of `python`.
2. **`RUNASADMIN`-flagged executables break stdio.** When `pycharm64.exe` carries the `RUNASADMIN` AppCompat flag (common on installs that always start elevated), a non-elevated MCP client cannot spawn it and gets `WinError 740`. The SSE transport avoids this entirely: it talks to the IDE's web server instead of launching the executable. `doctor` reads the flag from the registry and reports it.
3. **SSE needs loopback access.** The SSE entry requires the client to reach `127.0.0.1:<port>` and PyCharm to be open with the project loaded. Sandboxed clients that cannot reach loopback need a small stdio↔SSE proxy; see [comfyui-studio](https://github.com/love530love/comfyui-studio) for a working launcher.
4. **Windows console encoding.** Set `PYTHONUTF8=1` in the environment you manage, especially when custom nodes print non-ASCII text.
5. **PyCharm must stay installed.** The stdio connector launches the IDE executable; closing the IDE window is fine, uninstalling it is not.

## Development

```bash
pip install -r requirements-dev.txt
pytest -q
```

## 中文说明

PyCharm 2025.2+ 内置了 MCP Server（闭源），本项目是它的开源集成层：

- `detect` 自动定位 PyCharm（环境变量 `PYCHARM_EXE`、PATH、JetBrains Toolbox、已有客户端配置）
- `install --client qoder|workbuddy|cursor|all` 自动合并 `mcp.json`，写前备份，不碰其他服务器
- `--transport sse` 生成 `{"url": "http://127.0.0.1:64462/sse"}` 形式的条目，直连 PyCharm 内置 Web 服务
- `doctor` 检查可执行文件、项目路径、IDE 进程、SSE 端口、`RUNASADMIN` 兼容标记、客户端配置

常见坑：MCP 终端不继承 venv（用解释器绝对路径）；`pycharm64.exe` 带 `RUNASADMIN` 兼容标记时，非管理员客户端用 stdio 拉起会报 `WinError 740`，改用 `--transport sse`；SSE 需要客户端能访问 loopback，沙箱客户端可用 stdio↔SSE 代理（见 comfyui-studio）；Windows 下建议 `PYTHONUTF8=1`。

## License

MIT
