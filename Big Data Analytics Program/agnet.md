# 專案執行備忘

- 目前只研究授課語言轉換、學生修課路徑與學習表現的關聯，本目錄不開發教師推薦；競賽移至兄弟目錄 AI competition 並獨立維護。
- 本機資料庫 ncu_course_flow_1150012；開課 1051–1151，成績比較先至 1142。1151 成績不完整。
- 研究設計與完成狀態見 RESEARCH_PLAN.md。T 分數是換尺，變異數是分散程度，不能單獨代表教學好壞。
- 英語授課不等於核對正式 EMI；首次可見學期不等於入學；沒有修課不能推論免修、休學或畢業。
- Python 放 src/；notebook 放 notebooks/ 並排除內容。學生共用模組是 student_data.py。
- 原始資料、識別碼、備份、帳密、本機規則、outputs/、local_archive/、PDF 不提交。MySQL 使用本機 login-path。
- README.md 保留使用者刪改；必要時僅新增目前入口，其餘資訊放研究文件。
- 保留使用者指定的 agnet.md 檔名作維護備忘，不是應用端 Agent。
