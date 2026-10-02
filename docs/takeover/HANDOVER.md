# NGOPilot 本機試用交付

2026-10-02 · 產品方向由實際 Claude Opus 5.5 medium 請求審查，Codex 實作與驗收。交付範圍是可操作、有人陪同的本機試用；NGO 獨立可用性與節省時間驗證為 **NOT_READY**。

## 啟動

Python 3.12，macOS/Linux。從 repo 執行 `./scripts/start-workbench.sh`，開啟 http://127.0.0.1:8310 。首次需要網絡下載套件；日後直接啟動既有環境。`--port 8310` 可更換連接埠。

管理員用 `--env-file /absolute/path/provider.env` 讀取現有設定。本機已驗證的設定檔位於旁邊 CareFlow 的 `backend/.env`，未複製或改動其憑證。不要把此檔加入 Git。

| 流程 | 管理員設定 |
|---|---|
| 紙本照片／政府表格照片 | `AZURE_OPENAI_ENDPOINT`、`AZURE_OPENAI_API_KEY`、`AZURE_OPENAI_DEPLOYMENT`、`AZURE_OPENAI_MODEL` |
| 會議整理／政府表格文字 | `DEEPSEEK_API_KEY`，選填 `DEEPSEEK_TEXT_MODEL` |
| 錄音轉錄 | `DASHSCOPE_API_KEY` |
| 排班草稿 | 本機演算法，不使用模型 |

也保留原有 OpenRouter 整合，由 `OPENROUTER_API_KEY` 設定。未設定時不會生成看似成功的模擬結果。`LLM_PROVIDER=mock` 只供開發測試，畫面會標示模擬。不要用於聲稱真實 AI 演示。Azure 原生日期式端點使用本地 API 版本覆寫 `2025-04-01-preview`，可由 `NGOPILOT_AZURE_API_VERSION` 指定；沒有改動 CareFlow 的原始環境檔。

## 四個工作流程

1. **紙本轉 Excel**：上載 PNG/JPG → 看原圖和 13 個欄位 → 修正、填寫審核人、勾選來源核對 → 匯出。未審核資料不會自動批准；部分審核時只匯出已審核列，畫面顯示略過筆數。
2. **會議記錄**：上載錄音及 DOCX 範本 → 核對原始錄音與整理欄位 → 確認 → 匯出 Word。逐字稿只展示原生服務允許的節錄；未知事項保留未確認。
3. **政府表格**：選範本、輸入文字或照片 → 逐欄確認 → 匯出 PDF。內建範本有歷史版本；此工具填字，不判斷資格、不提交申請。未知身分證、電話、地址必須留空。
4. **排班草稿**：上載原 Roster 格式家居照顧與護送工作簿、選週開始日期 → 看全部阻塞／審核原因 → 可重新驗證。本機工作台不提供發布；有阻塞時連匯出也會拒絕。複雜排班修正仍使用既有 Agent/MCP 的結構化 review，不宣稱是自動完成的可執行排班。

API 使用本機同源請求及受限檔案根目錄；不應把 8310 暴露至公網。AI 處理會把相關內容送往管理員設定的服務。試用先用合成資料；正式個案需由機構決定資料處理安排。

## 資料及恢復

所有工作狀態預設在 `.local-workbench/`：`jobs.sqlite3`、工作台操作 SQLite、`jobs/` 原檔與匯出、`app-data/` 原生資料庫及逐字稿保管資料、`resources/` 範本、`runtimes/` 鎖定 Python 環境。全部 Git ignored。保護整個資料夾與存取權限。

備份時先在啟動終端按 Ctrl-C，確認所有工作停止，再**複製整個 `.local-workbench/`** 至備份位置。不要只複製單一 SQLite，因為原檔與加密逐字稿資料亦必須保留。恢復到一個空的新目錄，設定 `NGOPILOT_MCP_STATE_DIR=/absolute/restored-folder` 後啟動。不要覆寫現有活動資料。模型憑證由管理員另外保存，不放進分享備份。

瀏覽器重載後從「最近的工作」繼續。服務重啟會把未完成的工作台請求標成中斷；可讀取原工作狀態再決定重試。開始工作的 `request_id` 避免同一次提交重複執行；相同 id 搭配不同內容會拒絕。

## 維護與架構

`deployment/workbench/` 只負責 HTTP、檔案邊界、四卡 UI 與操作紀錄；不複製演算法。工具本體維持 `MCPcode/src/ngopilot_mcp/tools/<tool>/` 各自的 manifest、schemas、controller、validation、native_adapter、state、artifacts。`algo-dependencies/` 維持唯讀。

完整 Agent／帳戶 gateway 仍在 `deployment/frontend`、`deployment/backend`，需要既有 PostgreSQL/GCS/Agent 設定；並未在本輪對外部署。雲端檔案儲存仍只使用 GCS。不要把本機工作台測試當成公網部署或多機構隔離驗證。

測試：安裝 MCP 的 dev extra 及 `deployment/workbench/requirements.txt`、pytest/httpx 後，從根目錄執行 `python -m pytest MCPcode/tests deployment/workbench/tests`。舊前端使用 Node 24、pnpm 10.33.0，執行 typecheck/test/build。原生依賴更新必須重建既有 vendor payload/wheel/lock，不直接修改演算法目錄。
