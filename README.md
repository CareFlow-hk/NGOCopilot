# NGOPilot

**CareFlow 文件工作台，本機試用版（2026-10-02）**。紙本轉 Excel、錄音整理成 Word、政府表格填報和排班草稿，沿用四個獨立 MCP 工作流程。AI 先產生草稿，使用者核對後才匯出。

```sh
./scripts/start-workbench.sh --env-file /absolute/path/to/provider.env
```

開啟 **http://127.0.0.1:8310**。需要 Python 3.12；首次啟動會安裝隔離環境及鎖定的原生依賴。可用 `NGOPILOT_PYTHON=/path/to/python3.12` 指定 Python。省略 `--env-file` 也能開啟介面，未設定的 AI 流程會清楚提示，沒有自動 mock fallback。

- [操作、設定與備份](docs/takeover/HANDOVER.md)
- [兩分鐘演示與試用驗證](docs/takeover/DEMO.md)
- [實際驗收、材料時效及已知限制](docs/takeover/2026-10-02-evidence.md)
- [合成示範檔案](deployment/workbench/samples/README.md)

活動冊月曆已拆為獨立 **CareFlow Scheduler**（旁邊的 `Careflow Scheduler` repo，8311）。既有 Atlas 負責地區探訪視覺化；本次未改動 Atlas。這三者不共享個案資料或假設彼此已部署。

以下保留完整 Agent 的技術架構；日常試用由上面的四卡工作台開始。

![NGOPilot layered product architecture](docs/images/ngopilot-layered-product-architecture.png)

## Repository Layout

- `harness bone/`: NGOPilot agent runtime, CLI, and desktop application
- `MCPcode/`: NGOPilot MCP server and four stateful NGO workflow tools
- `algo-dependencies/CareFlow/`: CareFlow algorithm dependency source
- `algo-dependencies/RosterCopiilot/`: roster algorithm dependency source

The advanced NGOPilot Agent uses the MCP server as a first-party stdio extension.
The direct workbench calls the same controllers; MCP retains ownership of
workflow validation, durable jobs, review state, and delivered artifacts.

See [Agent-MCP Architecture Design Plan.md](Agent-MCP%20Architecture%20Design%20Plan.md)
for the product architecture and
[MCP-pre-build algorithm design plan.md](MCP-pre-build%20algorithm%20design%20plan.md)
for the MCP and algorithm boundaries.
