# 授課語言轉換與學生修課路徑及學習表現之關聯研究

## 研究問題

必修課由中文轉為英語授課前後，學生修課時點、後續路徑及成績分布是否不同？先逐課比較，再評估整合。未處理課綱、學生組成與評分差異前，不宣稱因果效果。

## 程式與完成狀態

| 程式 | 用途與狀態 |
| --- | --- |
| src/analyze_language_conversion.py | 已實作唯讀候選盤點，核對課名、必修、學制、學分、教師與前後成績；T 分數保留作探索 |
| src/analyze_conversion_first_attempt.py | 已實作首次可見選入者的 60 分門檻、停修、未知及衝突分類；固定四學期再次選入與追蹤可見性 |
| src/analyze_undergraduate_eight_plus.py | 既有八學期大學部樣本、路徑與成績背景 |
| src/analyze_undergraduate_stage_supply.py | 既有學院、推定年級供給代理與首次修讀關聯 |
| src/analyze_project_research_next.py | 既有供給敏感度、跨批次檢查與後續路徑 |
| src/analyze_trends_sequences.py | 趨勢及共用供給函式，仍為成績和首次修讀模組相依項 |
| src/student_data.py、src/english_taught_analysis.py | 共用學生整理、狀態判讀、唯讀查詢 |
| src/undergraduate_*.py | 八學期入口相依的成績、首次修讀與摘要特徵分群 |

## 下一步（尚未完成）

首次選入結果已完成原始分層彙總，尚未做背景調整或建立比較組。此處「首次」是資料範圍內首次可見；60 分是數字門檻代理，不是已核對的正式通過旗標。「四學期內再次選入」不直接等於教務上的重修。

1. 核對課綱、各屆必修對象、名額、教師與評分；初篩全英語是同季可見紀錄判定，不代替正式制度。
2. 逐課計算平均、中位數、標準差、四分位距、第 25／50／75 百分位數，分開呈現成績水準與差距。
3. 對齊轉換時點，調整前期成績、可比年級與重修，統一缺值與衝突紀錄處理。
4. 分析延後修讀、重修及後續銜接課；後續英語參與排除目標課。
5. 比較組、轉換前趨勢與識別條件支持時，才使用差異中的差異法或事件研究。

## 執行

先在授權環境配置本機 MySQL login-path codex-local；背景分析另需本機 undergraduate_department_rules.json。資料與規則不隨倉庫提供。

    uv sync --locked
    uv run --locked python .\src\analyze_language_conversion.py
    uv run --locked python .\src\analyze_conversion_first_attempt.py

首次選入結果留在 outputs/conversion_first_attempt/。先讀所有狀態並處理衝突，再找首次選入；不要求連續八學期。缺值和衝突保留在主要分母，另報已知成績分母。再次選入比例限日曆至少有四學期且學生紀錄在窗末或更晚仍可見者；這是可見性限制，不保證期間無缺漏，也不證明其他人未再次選入。首次紀錄在 1051 者另列左截斷警示。需正式應修母群才能分析延後選課。

背景分析依序：

    uv run --locked python .\src\analyze_undergraduate_eight_plus.py
    uv run --locked python .\src\analyze_undergraduate_stage_supply.py
    uv run --locked python .\src\analyze_project_research_next.py

彙總存本機 outputs/。轉換盤點採當期明確大學、有效選入與數字成績 0–100，去除完全相同學生－班次－成績－學分列；與背景分析的衝突排除尚未完全一致，正式整合前須統一。正式年級與英語能力仍有資料限制。
