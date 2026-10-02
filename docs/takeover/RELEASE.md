# 交付版本

2026-10-02。產品程式驗收所對應的 Git 版本：

| 專案 | 程式快照 | 分支 | 入口 |
|---|---|---|---|
| NGOPilot | `d62fc51` | `codex/takeover-ngopilot` | http://127.0.0.1:8310 |
| CareFlow Scheduler | `20045e0` | `codex/initial-release` | http://127.0.0.1:8311 |

後續提交只整理驗收文件、排除可重建的 egg-info，及把本機狀態／環境檔排除於 Docker build context，不改變已驗證工作流程。尚未推送遠端或部署公網。

Opus 5.5 最終產品簽核見 [opus-final-signoff.md](opus-final-signoff.md)。P0-1 審核門檻與 P0-2 日期／星期一致性已關閉；簽核依據為工程提供的結果，不宣稱獨立人類專家審查。

服務已用交付腳本啟動。停止可在各自啟動終端 Ctrl-C；重新啟動指令及資料備份位置見 [HANDOVER.md](HANDOVER.md)。公開演示只使用 samples 中的合成資料及 Scheduler 公開歷史活動冊。

最終 API 負面檢查：未審核紙本 export 回傳 INVALID_REQUEST；blocked 排班 export 回傳 HTTP 409。瀏覽器確認紙本原圖載入、原始值保留、沒有審核前匯出按鈕；會議原錄音播放器讀到 32.526893 秒，無媒體錯誤。

已核對待提交檔案不含當前 provider.env 的已知金鑰字面值，也不含 `.local-workbench`、`.data`、環境檔或虛擬環境。這是指定值及路徑檢查，不是任意秘密可被完全偵測的保證。

## 完整 Agent 封裝驗收

映像 `ngopilot-takeover:local`：`sha256:c9a11e9276e88aacd45887c9b0de4fcd05a2e694608866ded04290a1ba87bfcf`。完整 Rust release、MCP bootstrap 與 gateway 安裝完成。一次 PyPI 下載超時後重試成功，未改動既有雲端服務。

容器以 `ngopilot` 非 root、`--network none`、唯讀合成照片運行：Agent 1.45.0；4 個工具；mock 協定測試 start=pending_review，未審核 export=INVALID_REQUEST，review=reviewed，再 export=exported，輸出5,824 bytes XLSX，執行後 vendor payload 雜湊仍通過。此 smoke 不代表外部模型或 GCS 生產端到端驗證；本機真實模型證據另列於實際工作流程。

Scheduler 映像 `careflow-scheduler:local`：`sha256:5d3b64acf2601d40c082dbd69961ebbddb202c380ea8bb1d592fefb870c69fc6`，已通過全新無金鑰樣本檢查。
