# 授課語言轉換與學生修課路徑及學習表現之關聯研究

以校務開課、選課與成績探索必修課由中文轉為英語授課前後，修課路徑與成績分布是否不同。[研究規劃、完成狀態與入口](../RESEARCH_PLAN.md)。

已實作語言轉換候選盤點與八學期路徑、供給背景分析。完整成績分布、背景調整及事件研究尚待實作。T 分數與變異數不能單獨代表教學好壞；結果不等於因果效果。

    uv sync --locked
    uv run --locked python .\src\analyze_language_conversion.py

執行需授權本機 MySQL 與 login-path。原始資料、識別碼、備份、憑證、規則、PDF、notebook 內容、outputs/、local_archive/ 不上傳。

[環境管理](../UV_SETUP.md) · [清理紀錄](../PROJECT_CLEANUP.md) · [原有研究說明](../README.md)
