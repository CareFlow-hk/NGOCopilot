# Foundry Luna 與 Atlas 介面交付

2026-10-03。本文件取代舊驗收紀錄中的模型及語音配置說明。

> 更新：使用者填入 Key 後，已完成下方真實 Luna 驗收；前文空 Key 狀態保留作最初交付紀錄。

## 已完成

保留 Wilson 原 Rust Agent、Chatbot、ACP、MCP 和對話歷史。四個 CareFlow 工具及獨立 Scheduler 作為五個工具使用；首頁提示只填入訊息，由 Agent 決定工具。Claude Opus 5.5 medium 已作產品決策，原始輸出及工程取捨見 [決策紀錄](opus-luna-atlas-decision.md)。

聊天、文字整理、圖片／PDF 抽取全部指向 Foundry `gpt-6-luna`。原 Agent 使用 OpenAI provider 的 Responses 路徑；CareFlow 適配器及 Scheduler 使用 Responses API。每次繼續歷史對話，先透過官方 ACP `session/set_config_option` 設為 `openai` 和 Luna；失敗便停止，不沿用舊模型。工具請求不接受原生庫內的舊模型選擇，也不繼承舊供應商金鑰。

語音服務停用。請上傳 TXT、Markdown 或 DOCX 轉寫稿，以及獨立的 DOCX 記錄範本。Luna 整理文字，人工核對後才匯出。音訊上傳及音訊工具輸入會明確拒絕；沒有自動轉写或靜默 ASR 回退。合成例子：`deployment/agent-samples/transcript-synthetic.txt`。

UI 依照目前 Atlas 的 `src/styles.css`、`refinement.css`（HEAD 8127ef3 加目前工作目錄）採用白底、深綠、DM Sans／Noto Sans TC、72px 頂欄、280px 側欄及較大的按鈕。Atlas repo 沒有修改。Scheduler 同步配色；它仍是活動日曆，不是定時任務系統。

## 只需填 API Key

本機設定檔（Git ignored、權限 600）：

`/Users/jiahangx/Projects/NGOPilot/.local-agent/foundry.env`

已設定：

```dotenv
FOUNDRY_ENDPOINT=https://CareFlow-VPS.services.ai.azure.com/openai/v1
FOUNDRY_DEPLOYMENT=gpt-6-luna
FOUNDRY_API_KEY=
```

填好最後一項，於 NGOPilot 目錄執行 `scripts/restart-agent.sh`，刷新 http://127.0.0.1:8310。Scheduler 8311 使用同一檔案，每次抽取重新讀取。頁面「已配置」只表示已提供 Key，不代表連線／配額已驗證。設定錯誤會明確報錯，不換其他模型。

未填 Key 時，頁面顯示「待配置」，禁止聊天送出及需要 Agent 接續的核對確認；後端亦拒絕 prompt。歷史對話和既有成品仍可讀取下載。舊 8312 Azure 備援服務已停止，資料保留。

## 驗收範圍

- NGOPilot MCP + gateway：239 passed、1 skipped；包含文字／圖片 Responses 映射、強制部署、空 Key 不回退、不完整輸出拒絕、轉寫稿讀取及音訊拒絕。
- Scheduler：20 passed；包含 Foundry Responses、舊 Key 不啟用及不完整輸出拒絕。
- 前端：TypeScript、正式 build、2 項 Vitest 通過。最後任務確認與矮螢幕調整再通過 TypeScript/build。
- 最終原 Agent 實測：載入既有對話，透過官方 ACP 切換 provider/model 成功；空 Key prompt 在 gateway 被拒；既有政府表格 PDF 可下載且有 PDF 檔頭。
- 瀏覽器：核對待配置狀態、五工具提示填入但不送出、設定說明、Atlas 視覺。截圖：`luna-atlas.png`。
- `algo-dependencies/` 的 316 個快照檔案雜湊均一致，沒有修改依賴。

**尚未驗證：真實 Luna 推理、配額、模型在本帳戶的圖片能力和全部流程的 Luna 端到端輸出。** 原因是依使用者要求保留空 API Key，沒有借用其他憑證。舊模型的成功紀錄不能當作 Luna 的成功紀錄。

本輪只更新本機服務，沒有正式雲端部署。現有合成排班底稿仍只適合演示，不能冒充真實 NGO 人員資料或採用成果。

## 真實 Luna 驗收（2026-10-03，使用者授權後）

已重新啟動 Agent 載入使用者自行填入的 Key；Agent 8310 和 Scheduler 8311 均顯示已配置。未記錄或輸出 Key。

- 直接 Responses：文字回覆 `LUNA_OK`；合成圖片姓名回覆 `Test Person`；回傳模型均為 `gpt-6-luna`、狀態 completed。
- 轉寫稿 → Word：原 Agent 自主調用工具，待核對後經測試核對接口確認並匯出。未確認的房間／時間仍列為未解問題。
- 圖片 → Excel：Luna 識別出 Test Person，但其二次文字複核曾視為測試佔位值而清空。驗收保留原始抽取斷言，測試核對人依合成圖片確認姓名後匯出；這不是無需核對的準確度宣稱。
- 新 PDF → ICS／CSV：首次同一 PDF 復用了既有來源，因此另用只附加測試註解的新檔案標識重新抽取。新來源 `a5c6c74b38ee40549112232ea6408755` 成功辨識兩項活動，日期為 2026-10-12、2026-10-14，核對後匯出。

以下均經真實原 Agent ACP 對話 → MCP 工具 → 人工核對接口 → Agent 匯出；全部成品下載成功並核對 SHA-256。只使用作者建立的合成資料。沒有提交政府表格、發佈排班或向外傳送訊息。

|流程|對話|任務|完成秒數|成品|
|---|---|---|---:|---|
|meeting|20261003_23|job_ddb98289c35d46628e58d645fe6018e0|34.9|meeting-775cb63b8117_visit_note_4_20261003_130048.docx|
|paper|20261003_26|job_531ba4ef632e41b59d0c8feff91f51a6|35.7|paper-84365660a126_batch_5_20261003_130326.xlsx|
|scheduler|20261003_27|job_8ab3b32d0cd743f8ae145d39ac3d527a|34.4|scheduler-487840970d2d_a5c6c74b38ee40549112232ea6408755-aa8b7583.ics, scheduler-e8d5d52d1d02_a5c6c74b38ee40549112232ea6408755-6ae02eb3.csv|

本次尚未以 Luna 重跑政府表格及人手排班全流程；不能將上述三條流程的成功延伸為全部功能的端到端驗證。
