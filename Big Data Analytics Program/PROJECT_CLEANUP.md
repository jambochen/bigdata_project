# 專案清理紀錄（2026-11-19）

## 保留

語言轉換盤點、八學期背景分析及必要相依、研究方法文件、uv 版本檔、notebook 空目錄與合成資料檢查。原始資料、MySQL、本機規則與輸出報告未刪除。

## 移除的追蹤檔（可由 Git 歷史取回）

- run_dual_project_stats.py：抽出共用函式為 student_data.py，刪除教師推薦與雙專題入口。
- build_shared_analysis_layer.py、solo_teacher_offering_evidence.sql：舊教師／雙專題工具；未刪除資料庫物件。
- analyze_pathways_course_types.py、analyze_supply_vs_path.py、analyze_student_sequences.py：現行主分析不再相依的早期平行入口。
- 共用資料層與雙專題分析.md、競賽_EMI教師推薦_目標與Demo.md：舊競賽文件；後者先前已刪，本次記錄 Git 刪除。
- PROJECT_OVERVIEW.md：重複且過期入口。
- requirements.txt：統一使用 pyproject.toml、uv.lock。

## 本機封存

未追蹤的一次性匯入／建表、舊批次檢查、報告腳本與三份舊雙專題文件，移至 local_archive/cleanup_20261119/，不提交 Git，保留重建與回查能力。

## 相依與文件

新增 RESEARCH_PLAN.md；更新 .github/README.md、agnet.md。README.md 僅新增目前入口，保留使用者原有內容。學生分析改由 student_data.py 匯入。資料、輸出、PDF、notebook 內容與封存不進 Git。
