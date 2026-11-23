"""Research checks for supply measurement, first entry, and later pathways.

Reads the authorized local database and writes aggregate results only.
"""
from __future__ import annotations

import argparse
import json
from math import erfc, log, sqrt
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from analyze_undergraduate_eight_plus import COLLEGES, summarize
from analyze_undergraduate_stage_supply import (
    department_stage_supply, first_start_risk, offering_data, stage_supply,
)
from english_taught_analysis import DEFAULT_MYSQL, HERE, TERMS
from student_data import student_term_data


SUPPLY_PROXIES = {
    "same_department_stage": "department_up_to_year_offerings",
    "same_college_stage": "up_to_year_offerings",
    "same_college_all_bachelor": "all_local_bachelor_english",
}


def prepare(args):
    roster, attempts, _ = student_term_data(
        args, degree_scope="observed_undergraduate", exclude_english_major=False)
    _, _, _, cohort = summarize(roster)
    dept = roster[["student_key", "term_code", "department_code"]].copy()
    cohort = cohort.drop(columns="college").merge(
        dept, on=["student_key", "term_code"], how="left", validate="one_to_one"
    ).rename(columns={"department_code": "current_department_code"})
    cohort["college"] = cohort.current_department_code.fillna("").str[:1].map(COLLEGES)
    cohort["assumed_year"] = (cohort.position + 1) // 2
    english_major_ids = set(cohort.loc[
        cohort.current_department_code.eq("1002"), "student_key"])
    cohort["english_major"] = cohort.student_key.isin(english_major_ids)
    offerings = offering_data(args)
    department = department_stage_supply(offerings, cohort)
    cohort = cohort.merge(
        department, on=["term_code", "current_department_code", "assumed_year"],
        how="left", validate="many_to_one")
    risk = first_start_risk(cohort, stage_supply(offerings))
    assert len(cohort) == 9086 * 8 and len(risk) == 49928
    assert int(risk.first_start.sum()) == 6799

    scored = attempts.loc[
        attempts.target & attempts.score_ok & attempts.credits_num.gt(0) &
        attempts.teaching_language.eq("國語"),
        ["student_key", "term_code", "grade_num", "credits_num"],
    ].copy()
    scored["grade_credit"] = scored.grade_num * scored.credits_num
    prior = scored.groupby(["student_key", "term_code"], observed=True).agg(
        grade_credit=("grade_credit", "sum"),
        graded_credits=("credits_num", "sum"),
    ).reset_index()
    prior["prior_term_grade"] = prior.grade_credit / prior.graded_credits
    cohort = cohort.merge(
        prior[["student_key", "term_code", "prior_term_grade", "graded_credits"]],
        on=["student_key", "term_code"], how="left", validate="one_to_one"
    ).sort_values(["student_key", "position"])
    for column in ["prior_term_grade", "graded_credits"]:
        cohort["lagged_" + column] = cohort.groupby("student_key", sort=False)[
            column].shift(1)
    risk = risk.merge(
        cohort[["student_key", "term_code", "lagged_prior_term_grade",
                "lagged_graded_credits"]],
        on=["student_key", "term_code"], how="left", validate="one_to_one")
    risk["lagged_grade_per_10"] = risk.lagged_prior_term_grade / 10

    starts = risk.loc[risk.first_start.eq(1), ["student_key", "term_code"]]
    chosen = attempts.loc[
        attempts.selected & attempts.target & attempts.teaching_language.eq("英語"),
        ["student_key", "term_code", "offering_id"],
    ].merge(starts, on=["student_key", "term_code"], how="inner",
            validate="many_to_one")
    chosen = chosen.merge(
        offerings[["offering_id", "degree_level"]], on="offering_id",
        how="left", validate="many_to_one")
    bachelor_starts = set(chosen.loc[chosen.degree_level.eq("學士班"), "student_key"])
    risk["bachelor_first_start"] = (
        risk.first_start.eq(1) & risk.student_key.isin(bachelor_starts)).astype(int)
    return cohort, risk, offerings


def model_frame(data: pd.DataFrame, supply: str | None = None,
                interaction: bool = False, cohort_dummies: bool = True) -> pd.DataFrame:
    columns = ["position", "current_department_code", "lagged_grade_per_10"]
    if cohort_dummies:
        columns.append("first_observed_term")
    frame = data[columns].copy()
    categories = ["position", "current_department_code"]
    if cohort_dummies:
        categories.append("first_observed_term")
    else:
        frame["cohort_index"] = data.first_observed_term.map(
            {term: i for i, term in enumerate(TERMS)}).astype(float)
    frame = pd.get_dummies(frame, columns=categories, drop_first=True, dtype=float)
    if supply:
        frame["log_supply"] = np.log1p(data[supply].astype(float)).to_numpy()
        if interaction:
            frame["early_supply_interaction"] = (
                frame.log_supply.to_numpy() * data.position.le(4).to_numpy())
    return frame


def fit_and_infer(data: pd.DataFrame, supply: str, outcome: str,
                  interaction: bool = False) -> dict:
    design = model_frame(data, supply, interaction)
    x = design.to_numpy(dtype=float)
    y = data[outcome].to_numpy(dtype=int)
    estimator = LogisticRegression(C=1e6, max_iter=900, solver="lbfgs")
    estimator.fit(x, y)
    probability = estimator.predict_proba(x)[:, 1]
    full = np.column_stack([np.ones(len(x)), x])
    info = full.T @ (full * (probability * (1 - probability))[:, None])
    bread = np.linalg.pinv(info)
    scores = pd.DataFrame(full * (y - probability)[:, None])
    # Students share the exposure within each department- or college-term.
    unit = "current_department_code" if supply.startswith("department_") else "college"
    scores["exposure_group"] = (data[unit].astype(str) + ":" +
                                data.term_code.astype(str)).to_numpy()
    sums = scores.groupby("exposure_group", sort=False).sum().to_numpy()
    covariance = bread @ (sums.T @ sums) @ bread
    output = {
        "at_risk_student_terms": len(data),
        "events": int(y.sum()),
        "exposure_groups_for_uncertainty": int(scores.exposure_group.nunique()),
        "cluster_unit": unit + "_term",
    }
    for name in (["log_supply", "early_supply_interaction"] if interaction
                 else ["log_supply"]):
        index = design.columns.get_loc(name)
        beta = float(estimator.coef_[0, index])
        se = float(np.sqrt(max(0, covariance[index + 1, index + 1])))
        output[name] = {"coefficient": round(beta, 4), "standard_error": round(se, 4),
                        "wald_p": round(erfc(abs(beta / se) / sqrt(2)), 5) if se else None}
    beta = output["log_supply"]["coefficient"]
    output["supply_or_per_doubling"] = round(float(np.exp(beta * log(2))), 3)
    supply_se = output["log_supply"]["standard_error"]
    output["supply_or_95pct_interval"] = [
        round(float(np.exp((beta + direction * 1.96 * supply_se) * log(2))), 3)
        for direction in (-1, 1)]
    if interaction:
        beta_early = beta + output["early_supply_interaction"]["coefficient"]
        supply_index = design.columns.get_loc("log_supply") + 1
        interaction_index = design.columns.get_loc("early_supply_interaction") + 1
        early_se = float(np.sqrt(max(0, covariance[supply_index, supply_index] +
                                     covariance[interaction_index, interaction_index] +
                                     2 * covariance[supply_index, interaction_index])))
        output["early_or_per_doubling"] = round(float(np.exp(beta_early * log(2))), 3)
        output["early_or_95pct_interval"] = [
            round(float(np.exp((beta_early + direction * 1.96 * early_se) * log(2))), 3)
            for direction in (-1, 1)]
        output["late_or_per_doubling"] = output["supply_or_per_doubling"]
    return output


def compare_supply_definitions(risk: pd.DataFrame, output_dir: Path) -> dict:
    complete = risk.loc[
        risk.position.ge(2) & risk.lagged_graded_credits.ge(3) &
        risk.lagged_prior_term_grade.between(0, 100) & ~risk.english_major
    ].copy()
    summary = {"same_sample_student_terms": len(complete),
               "students": int(complete.student_key.nunique()),
               "any_english_first_starts": int(complete.first_start.sum()),
               "bachelor_first_starts": int(complete.bachelor_first_start.sum()),
               "models": {}}
    rows = []
    for label, supply in SUPPLY_PROXIES.items():
        first = complete.loc[complete.first_start.eq(1)]
        bachelor = complete.loc[complete.bachelor_first_start.eq(1)]
        missed = int(first[supply].eq(0).sum())
        bachelor_missed = int(bachelor[supply].eq(0).sum())
        summary["models"][label] = {
            "all_first_starts": fit_and_infer(complete, supply, "first_start"),
            "bachelor_cause_specific_first_starts": fit_and_infer(
                complete, supply, "bachelor_first_start"),
            "first_starts_with_zero_proxy_supply": missed,
            "bachelor_first_starts_with_zero_proxy_supply": bachelor_missed,
            "zero_proxy_pct_of_first_starts": round(100 * missed / len(first), 2),
            "zero_proxy_pct_of_bachelor_first_starts": round(
                100 * bachelor_missed / len(bachelor), 2),
        }
        rows.append({"supply_definition": label,
                     "first_starts": len(first),
                     "zero_supply_first_starts": missed,
                     "zero_supply_first_starts_pct": round(100 * missed / len(first), 2),
                     "bachelor_first_starts": len(bachelor),
                     "zero_supply_bachelor_first_starts": bachelor_missed,
                     "zero_supply_bachelor_first_starts_pct": round(
                         100 * bachelor_missed / len(bachelor), 2),
                     "adjusted_or_per_doubling": summary["models"][label][
                         "all_first_starts"]["supply_or_per_doubling"]})
    pd.DataFrame(rows).to_csv(output_dir / "supply_definition_sensitivity.csv",
                              index=False, encoding="utf-8-sig")
    return summary


def out_of_cohort_validation(complete: pd.DataFrame,
                             output_dir: Path) -> dict:
    cohorts = sorted(complete.first_observed_term.unique().tolist())
    boundary = max(1, int(len(cohorts) * 0.8))
    train = complete.loc[complete.first_observed_term.isin(cohorts[:boundary])]
    test = complete.loc[complete.first_observed_term.isin(cohorts[boundary:])]
    if train.first_start.nunique() < 2 or test.first_start.nunique() < 2:
        return {"status": "insufficient_test_cohorts", "cohorts": cohorts}
    summary = {"status": "ok", "train_cohorts": cohorts[:boundary],
               "test_cohorts": cohorts[boundary:],
               "train_student_terms": len(train), "test_student_terms": len(test),
               "test_first_starts": int(test.first_start.sum()), "models": {}}
    college_rows = []
    for label, supply in [("baseline", None),
                          ("with_college_stage_supply", "up_to_year_offerings"),
                          ("with_department_stage_supply",
                           "department_up_to_year_offerings")]:
        xtrain = model_frame(train, supply, cohort_dummies=False)
        xtest = model_frame(test, supply, cohort_dummies=False).reindex(
            columns=xtrain.columns, fill_value=0)
        estimator = LogisticRegression(C=1, max_iter=900, solver="lbfgs")
        estimator.fit(xtrain.to_numpy(dtype=float), train.first_start.to_numpy(dtype=int))
        probability = estimator.predict_proba(xtest.to_numpy(dtype=float))[:, 1]
        actual = test.first_start.to_numpy(dtype=int)
        summary["models"][label] = {
            "brier": round(float(brier_score_loss(actual, probability)), 5),
            "log_loss": round(float(log_loss(actual, probability)), 5),
            "roc_auc": round(float(roc_auc_score(actual, probability)), 5),
        }
        by_college = pd.DataFrame({
            "college": test.college.to_numpy(), "actual": actual,
            "predicted": probability,
            "sq_error": (actual - probability) ** 2,
        }).groupby("college", observed=True).agg(
            student_terms=("actual", "size"), observed_rate=("actual", "mean"),
            predicted_rate=("predicted", "mean"), brier=("sq_error", "mean")
        ).reset_index()
        by_college["model"] = label
        college_rows.append(by_college)
    per_college = pd.concat(college_rows, ignore_index=True)
    for field in ["observed_rate", "predicted_rate", "brier"]:
        per_college[field] = per_college[field].round(5)
    per_college.to_csv(output_dir / "holdout_predictions_by_college.csv",
                       index=False, encoding="utf-8-sig")
    return summary


def explain_supply(risk: pd.DataFrame, output_dir: Path) -> dict:
    complete = risk.loc[
        risk.position.ge(2) & risk.lagged_graded_credits.ge(3) &
        risk.lagged_prior_term_grade.between(0, 100) & ~risk.english_major
    ].copy()
    interaction = fit_and_infer(complete, "up_to_year_offerings", "first_start",
                                interaction=True)
    holdout = out_of_cohort_validation(complete, output_dir)
    return {"same_sample": len(complete),
            "lagged_grade_is_previous_mandarin_professional_course_average": True,
            "early_is_positions_1_to_4": True,
            "interaction": interaction,
            "chronological_cohort_holdout": holdout,
            "interpretation": "Prediction and association, not a supply intervention effect"}


def post_start_pathways(cohort: pd.DataFrame, output_dir: Path) -> dict:
    states = cohort.pivot(index="student_key", columns="position",
                          values="english_yes").sort_index()
    terms = cohort.pivot(index="student_key", columns="position",
                         values="term_code").reindex(states.index)
    if list(states.columns) != list(range(1, 9)) or states.isna().any().any():
        raise ValueError("The cohort must have all eight observed semesters")
    rows = []
    for student_key, active, student_terms in zip(
            states.index, states.to_numpy(dtype=bool), terms.to_numpy()):
        if not active.any():
            continue
        first = int(np.argmax(active) + 1)
        if first == 8:
            continue  # No next observed semester in the fixed window.
        next_active = bool(active[first])
        reentry_observable = first <= 6 and not next_active
        rows.append({"student_key": student_key,
                     "first_start_position": first,
                     "first_start_calendar_semester": str(student_terms[first - 1])[-1],
                     "start_period": "early_1_to_4" if first <= 4 else "late_5_to_7",
                     "next_term_continued": int(next_active),
                     "reentry_next_term_observable": int(reentry_observable),
                     "reentered_one_term_after_stop": int(
                         reentry_observable and active[first + 1])})
    data = pd.DataFrame(rows)
    by_position = data.groupby("first_start_position", observed=True).agg(
        first_starters_with_next_term=("student_key", "size"),
        continued_next_term=("next_term_continued", "sum"),
        stoppers_with_one_more_term=("reentry_next_term_observable", "sum"),
        reentered_next_term=("reentered_one_term_after_stop", "sum"),
    ).reset_index()
    by_period = data.groupby("start_period", observed=True).agg(
        first_starters_with_next_term=("student_key", "size"),
        continued_next_term=("next_term_continued", "sum"),
        stoppers_with_one_more_term=("reentry_next_term_observable", "sum"),
        reentered_next_term=("reentered_one_term_after_stop", "sum"),
    ).reset_index()
    by_period_semester = data.groupby(
        ["start_period", "first_start_calendar_semester"], observed=True).agg(
            first_starters_with_next_term=("student_key", "size"),
            continued_next_term=("next_term_continued", "sum"),
            stoppers_with_one_more_term=("reentry_next_term_observable", "sum"),
            reentered_next_term=("reentered_one_term_after_stop", "sum"),
    ).reset_index()
    for table in [by_position, by_period, by_period_semester]:
        table["continued_pct"] = (
            100 * table.continued_next_term /
            table.first_starters_with_next_term).round(2)
        table["reentry_one_term_pct"] = (
            100 * table.reentered_next_term /
            table.stoppers_with_one_more_term.replace(0, np.nan)).round(2)
    by_position.to_csv(output_dir / "post_start_equal_followup_by_position.csv",
                       index=False, encoding="utf-8-sig")
    by_period.to_csv(output_dir / "post_start_equal_followup_by_period.csv",
                     index=False, encoding="utf-8-sig")
    by_period_semester.to_csv(
        output_dir / "post_start_by_period_and_calendar_semester.csv",
        index=False, encoding="utf-8-sig")
    return {"first_starters_with_next_term": len(data),
            "first_starters_in_term_8_excluded_from_next_term": int(
                states.any(axis=1).sum() - len(data)),
            "continued_next_term": int(data.next_term_continued.sum()),
            "stoppers_with_equal_reentry_followup": int(
                data.reentry_next_term_observable.sum()),
            "reentered_one_term_after_stop": int(
                data.reentered_one_term_after_stop.sum()),
            "reentry_rule": "Among immediate stoppers, only first starts in terms 1-6; "
                            "observe exactly one later term for reentry",
            "interpretation": "Descriptive pathway comparison; no causal inference"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--login-path", default="codex-local")
    parser.add_argument("--database", default="ncu_course_flow_1150012")
    parser.add_argument("--department-rules", type=Path,
                        default=HERE / "undergraduate_department_rules.json")
    parser.add_argument("--output-dir", type=Path,
                        default=HERE / "outputs" / "undergraduate_research_next")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cohort, risk, _ = prepare(args)
    result = {
        "cohort_students": int(cohort.student_key.nunique()),
        "supply_sensitivity": compare_supply_definitions(risk, args.output_dir),
        "extra_supply_explanation": explain_supply(risk, args.output_dir),
        "post_start_pathways": post_start_pathways(cohort, args.output_dir),
        "student_identifiers_exported": False,
    }
    (args.output_dir / "research_next_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
