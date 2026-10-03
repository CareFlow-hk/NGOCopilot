# NGOPilot Agent 交付

2026-10-03。此文件取代 `docs/takeover/HANDOVER.md` 的四卡工作台入口。

## 使用

本機 **http://127.0.0.1:8310** 是 Wilson 原來的 Chatbot，使用原有 Rust Agent、ACP、MCP 和對話歷史。首頁示例只填入文字；模型自行決定工具。將附件拖入對話或按「加入附件」，以一句話描述工作。資料不足時 Agent 追問，抽取後在對話任務卡逐項核對，填核對人、按確認，Agent 才繼續產生文件。

- 紙表格：JPG/PNG 探訪表格 → Excel。
- 記錄：TXT／Markdown／DOCX 轉寫稿及獨立 DOCX 範本，說明內部會議或家訪 → Word。
- 政府表格：先讓 Agent 列出目前支援模板，提供資料 → 預覽、核對、PDF。沒有提交到政府。
- 人手排班：既有 HC 家居照顧時間表、護送總表、目標週 → 排班草稿。保留舊算法要求的工作表結構；不是任意 Excel 排班。
- 活動 Scheduler：PDF 及年份 → 抽取、核對、ICS 和 CSV。卡片連結會開啟 **同一來源** 的 8311 月曆／原頁核對，不必重新上傳。額滿、取消或未核對活動不會進入匯出；日曆不是報名。

刷新後，原有對話及任務卡仍可讀取；下載只接受已登記且 SHA-256 未變的文件。核對失效或資料已變更時需要重新核對。模型不能在 MCP 中自行授權。若口頭修正，Agent 可提出新草稿，仍由人按確認。排班發佈／轉寫原件銷毀有獨立操作確認，普通匯出不包含這些行為。

## 現有本機配置

- `ngopilot-agent-local`：8310，Agent 及所有 AI 工具統一 Foundry `gpt-6-luna`，使用 Responses API；尚待管理員填 API Key。
- 舊 8312 備援 Agent 已停止，測試資料保留。
- Scheduler：8311，旁邊 `Careflow Scheduler` repo，保留原資料目錄。
- 主 Agent 狀態：`.local-agent/`；填入 API Key 後執行 `scripts/restart-agent.sh` 並刷新頁面。Scheduler 使用同一個設定檔，每次抽取重新讀取。API Key 不會回傳到前端。詳見 [最新模型及介面驗收](LUNA-ATLAS.md)。

## 建置與啟動

需要 Docker、Node 24.10+。原 Agent 基底映像已在本機建好；新機先建基底：

```sh
docker build -f deployment/backend/Dockerfile -t ngopilot-takeover:local .
cd deployment/frontend
corepack pnpm install --frozen-lockfile
npm run typecheck
npm run build
cd ../..
docker build -f deployment/backend/Local.Dockerfile -t ngopilot-agent:luna .
```

先在 Scheduler repo 執行 `./scripts/start.sh --env-file /Users/jiahangx/Projects/NGOPilot/.local-agent/foundry.env`，再啟動 Agent：

```sh
NGOPILOT_ROSTER_SAMPLE=true \
NGOPILOT_SCHEDULER_URL=http://host.docker.internal:8311 \
scripts/start-agent.sh --env-file /Users/jiahangx/Projects/NGOPilot/.local-agent/foundry.env
```

`NGOPILOT_SCHEDULER_URL` 未設定時，只載入原四工具。Scheduler bridge 是本機單一工作區整合，不可指向公網或多租戶服務。`NGOPILOT_SCHEDULER_BROWSER_URL` 預設 `http://127.0.0.1:8311`。目前在 macOS Docker Desktop 實測；Linux 需另行配置 host networking，不宣稱已驗證。

已存在的容器用 `docker start ngopilot-agent-local`。套用新映像需先停止、移除**這個容器**再執行啟動命令；`.local-agent/` 是外掛持久資料，不隨容器刪除。不要清理資料卷。此流程不碰已有 CareFlow／Atlas 服務。

Azure 備援：`NGOPILOT_AGENT_BACKEND=azure`，另設 `NGOPILOT_LOCAL_PORT=8312`、`NGOPILOT_LOCAL_CONTAINER=ngopilot-agent-azure`、`NGOPILOT_LOCAL_DATA_DIR=/absolute/repo/.local-agent/azure-backup`。Azure 使用 v1 相容接口；舊 deployment/api-version 路由不適用現有帳戶。正式切换主服務前保留兩套各自資料，沒有自動搬遷歷史。

管理員可用既有 provider env 的 `NGOPILOT_ROSTER_DIVISION_TEMPLATE`、`NGOPILOT_ROSTER_MASTER_DATA`、`NGOPILOT_ROSTER_DATA_LABEL` 設定人員底稿。Docker 內路徑必須由管理員額外唯讀掛載。`NGOPILOT_ROSTER_SAMPLE=true` 只用於合成演示，並覆寫上述底稿設定；正式配置應關閉。

## 備份及限制

停止寫入後完整備份 `.local-agent/` 及 Scheduler `.data/`；包含附件、原生資料庫、MCP 任務／核對授權、生成文件和對話。模型 env 檔另由管理員保管。恢復到新資料目錄，以 `NGOPILOT_LOCAL_DATA_DIR`／`SCHEDULER_DATA_DIR` 指向它，不要覆蓋唯一備份。

Docker 服務運作時，用應用 API 或容器內的資料庫工具檢查狀態；不要同時從 macOS 主機直接打開掛載中的 SQLite 檔案。跨主機／VM 的 WAL 共享記憶體不安全。備份前先停服務。

刪除本機對話不等於刪除工作資料；介面會說明。錄音轉寫銷毀也不會移除對話、摘要、匯出文件或備份。這是單機 NGO 試用及演示交付，沒有本輪公網部署、跨機構隔離驗收或真實 NGO 採用結果。原生 PostgreSQL/GCS 生產部署仍走既有 gateway，需另行部署驗收；本輪未改換雲端儲存。

## 演示順序

1. 從空白 Chatbot 開始，說「把這張探訪表整理成 Excel」，上傳 `deployment/workbench/samples/form-synthetic.png`，演示人工修改和確認。
2. 用 `deployment/agent-samples/transcript-synthetic.txt` + DOCX 範本產生會議記錄；展示未確認的房間預訂仍保留為未知。
3. 用合成姓名 TEST PERSON 產生樂悠咭預覽和 PDF；沒有真實身份資料。
4. 用 `deployment/agent-samples/HC-synthetic.xlsx`、`Escort-synthetic.xlsx`，目標週 2026-10-05，產生排班草稿。
5. 用 `deployment/agent-samples/activity-brochure-synthetic.pdf`、年份 2026，產生兩個活動和日曆；按卡片連結看同批資料。

9 月以前的原活動冊只稱歷史資料；所有合成文件均標示測試用途。10 月 7 日與 50 進 20 來自本次使用者需求，不將它擴寫為其他未確認的主辦方要求。
