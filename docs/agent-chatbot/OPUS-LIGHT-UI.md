# CareFlow Pilot 淺色介面（Opus 實作）

2026-10-03，Claude Opus 5.5 high 直接實作。Codex 只負責 build、瀏覽器驗收和轉達，沒有修改原始碼。
基準：`ae305ac`。未 commit，未部署。`algo-dependencies/`、後端、授權和 Agent/ACP/MCP 邏輯都沒有改動。

## 視覺參考

現行 Atlas 主題（唯讀）：
`/Users/jiahangx/.codex/worktrees/atlas-photo-intake/Careflow-Atlas/src/theme-atlas.css`
（由該 worktree 的 `src/main.tsx` 最後載入；`/Users/jiahangx/Projects/Careflow-Atlas` 已過時）。

Token：paper `#f7f4ec`、card `#fffdf8`、ink `#1d2622`、rule `#ddd6c6`、soft `#efe8da`、
accent `#7d3b27`；標題 Noto Serif TC，介面 Inter；52px 頂欄；圓角 2–4px。
次要文字由 `#7a766b` 加深至 `#5f5b52`／`#6b675d`，以保證小字對比度。

## 決策

1. **只有淺色模式。** 原畫面深淺混雜，原因是 `ThemeContext` 跟隨系統深色設定，整套 token 變成深色，
   而標題列和卡片又被單獨強制改成淺色。現在在根部處理：
   - `ThemeContext` 永遠是 light，不理會系統設定、已儲存的 `theme: dark` 和跨視窗廣播，也不再加 `.dark`；
   - `theme-tokens.ts` 刪除深色 token，MCP 應用只收到淺色值；
   - `main.css` 加入 `:root { color-scheme: light }`（原生 select 和捲軸），刪除全部 `.dark` 規則；
     `@custom-variant dark` 保留為 class 觸發，所以 `dark:` utility 永遠不會跟隨系統；
   - 兩個 `index.html` 都改為淺色啟動；設定頁移除主題切換卡，不提供壞掉的開關。
2. **對話版面。** 紙色畫布、760px 正文欄。Agent 回覆不加框，用戶訊息用 soft 色塊。
   時間戳改用細小的無襯線字。Markdown 表格改為細線帳簿樣式。
   側欄精簡：選中項用 soft 底加 2px accent 邊線。
3. **輸入框被裁切。** `MainPanelLayout` 使用 `h-dvh`，在 52px 頂欄下會裁掉輸入框；
   殼層內已改為 `height: 100%`。傳送按鈕用 `ngo-send-button` class 選取，不再依賴英文 aria-label。
4. **任務卡**（`ngo/WorkflowTaskCard.tsx`）。狀態、確認和輪詢邏輯逐字不變，只改畫面結構：
   - 狀態標記和說明：處理中、已匯出（內容已鎖定）、已發佈；
   - 標籤在上、輸入框精簡，桌面兩欄；
   - 活動用編號索引列，可展開／收起；
   - 「核對人」和確認按鈕同一行，仍需人手確認，Agent 才會繼續。
5. **下載檔案。** 任務卡按 artifact kind 顯示中文名稱，例如「活動日曆（ICS）」「活動清單（CSV）」
   「探訪表格整理（Excel）」「會議／家訪記錄（Word）」，另附用途和大小；雜湊檔名只放在 tooltip。
   下載仍走原本的 `/api/artifacts/url` 和認證，404 時明確提示「已無法下載，請在對話中要求重新匯出」。
   對話內的連結改為檔案列：類型、可讀名稱、「下載」。路徑和 aria-label 格式不變。
6. **zh-HK 文案。** 網頁版 build 不會編譯任何 i18n catalog：`src/i18n/compiled/` 只由 Electron
   腳本產生，而且被 gitignore。所以 react-intl 在網頁上一律顯示英文 defaultMessage。
   `ArtifactPathLink` 在繁體中文 locale（zh-HK/TW/MO/Hant）且沒有載入 catalog 時，改用內建的
   繁體字串（與 `messages/zh-TW.json` 相同）；已載入的 catalog 仍然優先。
   沒有更改用戶的語言設定，也沒有把整個網頁版改為載入 catalog（會一次翻譯整個 app，超出範圍）。

## 驗證

- `npm --prefix deployment/frontend run typecheck`、`test`（2/2）、`build`：全部通過。
- 桌面版 vitest 在這裡無法執行（沒有安裝依賴）；`MarkdownContent.test.tsx` 已更新為新的標籤文字。
- Codex 瀏覽器驗收（同一份 build，1440×1000 和 390×844）：
  - 根元素為 light class，`color-scheme: light`，畫布實測 `rgb(247,244,236)`；
  - 活動表單可讀，輸入框完整，檔案列精簡。
  - 截圖：`opus-light-chat.png`。
- 已知問題：上述瀏覽器驗收時，對話內檔案列仍顯示英文（第 6 點），本次已修正；需在 zh-HK 下再看一次。

## 修改的檔案

`harness bone/ui/desktop/`：`index.html`、`src/contexts/ThemeContext.tsx`、`src/theme/theme-tokens.ts`、
`src/styles/main.css`、`src/components/ngo/WorkflowTaskCard.tsx`、`src/components/ArtifactPathLink.tsx`、
`src/utils/artifactPaths.ts`、`src/components/{BaseChat,ChatInput,GooseMessage,UserMessage}.tsx`、
`src/components/Layout/NavigationPanel.tsx`、`src/components/settings/app/AppSettingsSection.tsx`、
`src/i18n/messages/zh-TW.json`、`src/components/MarkdownContent.test.tsx`。
`deployment/frontend/`：`index.html`、`src/auth.css`、`src/browser-shim.ts`。
