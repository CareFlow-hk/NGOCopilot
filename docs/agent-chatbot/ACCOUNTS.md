# 本機 Agent 帳號系統

2026-10-04。參考 CareFlow Atlas 的帳號設計（`docs/ACCOUNTS.md`，atlas-photo-intake 工作樹），在 8310 本機 Agent 加入機構帳號。Atlas repo 沒有修改。

## 決定

- 沿用 Atlas：只有管理員邀請，**不設公開註冊**；電郵只作登入名稱，不代表已驗證郵箱。沒有 SMTP、SSO、MFA。
- 角色：ADMIN 管理帳號，MEMBER 使用工作台。權限全部由伺服器檢查，介面隱藏不作授權依據。
- **每個帳號有獨立 Agent 工作區**：`.local-agent/tenants/<帳號 ID>/`，包括對話、附件、MCP 任務／核對、產生的文件及 Agent 程序。下載連結和 WebSocket ticket 綁定帳號。
- 第一位管理員沿用原有本機工作區 ID，所以加入帳號前的對話和文件歸該管理員所有，不需搬遷。
- 帳號庫：`.local-agent/accounts.sqlite3`（SQLite，WAL），和既有資料一起備份。
- 服務仍然只發佈在 `127.0.0.1`。帳號用途是同一部電腦上多位同事分開使用，不是公網多租戶服務。
- 雲端 gateway（Railway/Render，PostgreSQL + bearer token）保持原狀，本輪沒有改動。

## 流程

1. 運維建立第一位管理員（只能在帳號庫為空時執行一次）：

   ```sh
   scripts/agent-account.sh bootstrap admin@example.org 管理員姓名
   ```

   輸出 1 小時有效的一次性連結 `http://127.0.0.1:8310/#set-password=…`。連結 token 放在 URL fragment，打開後立即從網址列移除，不經 HTTP 路徑或 Referer。
2. 打開連結，設定 15–128 字元密碼，再以電郵和密碼登入。
3. 標題欄右上角帳號選單 › 帳號設定：
   - 所有人：修改密碼、查看登入狀態、登出其他裝置。
   - 管理員：邀請成員或管理員（產生一次性連結，請私下交付）、修改角色、停用／啟用、重新邀請／重設密碼、查看最近 100 條帳號操作記錄。
4. 忘記密碼由管理員重設。管理員本人無法登入時：

   ```sh
   scripts/agent-account.sh recover-admin admin@example.org
   ```

## 安全邊界

- 密碼以 Argon2id 儲存；session 及連結 token 只存 SHA-256 摘要。登入失敗不透露帳號是否存在。
- Cookie：`HttpOnly`、`SameSite=Strict`、`Path=/`。因只限 loopback HTTP，沒有 `Secure`；`create_local_app` 拒絕非 loopback 位址。
- 所有寫入請求必須帶完全相同的 `Origin`，帳號接口另須 JSON。沿用既有 Host／Origin／`Sec-Fetch-Site` 邊界。Atlas 另有 CSRF token；本機版以 Origin 檢查 + SameSite=Strict 代替，避免改動原 renderer 的所有請求。
- Session 6 小時無活動或登入滿 12 小時過期；每帳號最多 10 個 session。改密碼、重設、停用、角色或姓名變更會撤銷該帳號全部 session；開啟中的 Agent WebSocket 最遲 30 秒內斷開，下一條訊息即被拒。
- 不能停用或降級最後一位已啟用管理員。
- 登入按帳號（10 次／15 分鐘）及來源（60 次）限流，計數存於 SQLite。Docker 內所有本機請求來源相同，來源限額實際由全部使用者共用。
- 審計記錄不含密碼、session token 或連結。
- 帳號庫版本比程式新時拒絕開啟。

## 限制

- **活動 Scheduler（8311）仍是本機共用工作區**，不按帳號分開，8311 頁面本身也沒有登入。不要把它當作帳號隔離的一部分。
- 同一台電腦的使用者若有 macOS 帳戶或 Docker 權限，可直接讀取 `.local-agent/`；帳號系統不能防範主機管理員。
- 共用瀏覽器時請登出；登出不會清除瀏覽器的語言等本機偏好。

## 驗證（2026-10-04）

- Gateway：`deployment/backend/tests` 全部通過，其中 `test_local_accounts.py` 13 項覆蓋無公開註冊、一次性連結、Origin/JSON、成員不能管理、工作區及下載隔離、改密／停用撤銷 session、最後管理員保護、重設連結覆蓋舊連結、審計無密碼、限流、過期、資料庫版本。
- 前端 typecheck、Vitest、production build 通過。
- 真實容器（臨時資料目錄，8320）+ 瀏覽器：bootstrap 連結 → 設定密碼 → 登入 → 帳號選單 → 邀請成員 → 一次性連結 → 成員登入，成員看不到管理區、管理 API 403、工作區 ID 不同、ACP `initialize` 成功 → 登出回到登入頁；375px 寬無橫向捲動。只用合成帳號，測試容器已移除。
