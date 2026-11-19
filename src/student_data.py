"""Student-data preparation shared by the undergraduate research scripts.

Read-only database access; aggregate exports only.
"""
from pathlib import Path
import pandas as pd
from english_taught_analysis import (
    LEVELS, TERMS, assign_prior_levels, frame, prepare, read_sources,
)

TERM_ORDER = {term: i for i, term in enumerate(TERMS)}

def save_csv(data: pd.DataFrame, path: Path) -> None:
    data.to_csv(path, index=False, encoding="utf-8-sig")


def student_term_data(args, degree_scope="confirmed", exclude_english_major=True):
    mapping, student_terms, offerings, raw = read_sources(args)
    cohort, _, attempts = prepare(
        mapping, student_terms, offerings, raw, degree_scope=degree_scope,
        exclude_english_major=exclude_english_major)
    language_course = (
        attempts.course_code.str.startswith("LN") |
        attempts.course_name.str.contains(
            "大一英文|進修英文|TOEIC|英文能力鑑定|英語能力鑑定", regex=True) |
        attempts.english_level.isin(LEVELS[:-1])
    )
    if (attempts.selected & attempts.target & language_course).any():
        raise ValueError("語言學習課程混入英語授課專業課分析")
    cohort = assign_prior_levels(cohort, attempts)
    selected = attempts.loc[attempts.selected & attempts.target].copy()
    selected["english"] = selected.teaching_language.eq("英語")
    selected["emi"] = selected.emi_raw.eq("是")
    selected["english_non_emi"] = selected.english & selected.emi_raw.eq("否")
    selected["credits_valid"] = selected.credits_num.where(selected.credits_num.between(0, 50), 0)
    selected["english_credits"] = selected.credits_valid.where(selected.english, 0)
    selected["emi_credits"] = selected.credits_valid.where(selected.emi, 0)
    per_term = selected.groupby(["student_key", "term_code"], observed=True).agg(
        course_count=("offering_id", "size"),
        english_courses=("english", "sum"),
        emi_courses=("emi", "sum"),
        english_non_emi_courses=("english_non_emi", "sum"),
        total_credits=("credits_valid", "sum"),
        english_credits=("english_credits", "sum"),
        emi_credits=("emi_credits", "sum"),
    ).reset_index()
    roster = cohort.merge(per_term, how="left", on=["student_key", "term_code"],
                          validate="one_to_one")
    numeric = ["course_count", "english_courses", "emi_courses", "english_non_emi_courses",
               "total_credits", "english_credits", "emi_credits"]
    roster[numeric] = roster[numeric].fillna(0)
    roster["english_yes"] = roster.english_courses.gt(0)
    roster["emi_yes"] = roster.emi_courses.gt(0)
    roster["order"] = roster.term_code.map(TERM_ORDER).astype(int)
    excluded_language_attempts = int((attempts.selected & language_course).sum())
    return roster, attempts, excluded_language_attempts


def grouped_participation(roster: pd.DataFrame, group: str | list[str]) -> pd.DataFrame:
    out = roster.groupby(group, dropna=False, observed=True).agg(
        student_terms=("student_key", "size"),
        participating_terms=("english_yes", "sum"),
        english_courses=("english_courses", "sum"),
        english_credits=("english_credits", "sum"),
    ).reset_index()
    out["participation_pct"] = (
        100 * out.participating_terms / out.student_terms).round(2)
    return out.sort_values(group)


def source_completeness_by_term(args) -> pd.DataFrame:
    """原始修課檔的學分與數字成績覆蓋率；用於判定當期能否分析結果。"""
    term_values = ",".join(f"'{term}'" for term in TERMS)
    data = frame(args.mysql, args.login_path, args.database, f"""
        SELECT term_key AS term_code, COUNT(*) AS grade_rows,
               SUM(credits IS NULL OR TRIM(credits) = '') AS blank_credit_rows,
               SUM(grade IS NULL OR TRIM(grade) = '') AS blank_grade_rows
        FROM student_course_grade_raw
        WHERE term_key IN ({term_values})
        GROUP BY term_key ORDER BY term_key
    """)
    for col in ["grade_rows", "blank_credit_rows", "blank_grade_rows"]:
        data[col] = pd.to_numeric(data[col])
    data["credit_nonblank_pct"] = (100 * (data.grade_rows - data.blank_credit_rows) / data.grade_rows).round(2)
    data["grade_nonblank_pct"] = (100 * (data.grade_rows - data.blank_grade_rows) / data.grade_rows).round(2)
    return data
