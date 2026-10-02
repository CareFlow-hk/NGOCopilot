# 合成示範資料

全部個人欄位、錄音及姓名均為軟體測試，不是真實服務對象。

- `form-synthetic.png`：紙本流程輸入；圖片中的 mock 字樣是測試文字。交付的真實流程使用 Azure 模型，非 mock provider。
- `paper-reviewed.xlsx`：實際模型整理、開發者修正後的下載樣本。
- `meeting-script.txt`、`meeting-synthetic.wav`：32.53 秒合成錄音及原稿。
- `meeting-template.docx`、`meeting-reviewed.docx`：輸入範本及 DashScope + DeepSeek 整理、開發者確認後的 Word。
- `government-reviewed.pdf`：歷史樂悠咭範本，只填 TEST PERSON，身分證、電話與地址留空，未提交。

無模型設定時可直接打開輸出檔了解結果；重新抽取需管理員設定模型。這些既有輸出不得冒充新一次即時呼叫。沒有附帶真實排班工作簿。

Word 已檢查 XML 欄位完整，並渲染檢查中文無截字。若第三方轉 PDF 工具把中文顯示成空白，需為轉檔環境載入 CJK 字型；這不是缺少欄位資料。
