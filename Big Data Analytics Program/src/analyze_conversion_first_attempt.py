"""First observed selections in conversion courses; read-only, aggregate exports only."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from english_taught_analysis import DEFAULT_MYSQL, HERE, frame, SELECTED, WITHDRAWN, WAIVER

def order(term):
    return int(str(term)[:3])*2+int(str(term)[-1])

def resolve(raw):
    """Resolve all source rows before choosing first observed selected course term."""
    d=raw.fillna("").copy()
    for c in d.columns:
        d[c]=d[c].astype(str).str.strip()
    d["selected"]=d.allocation.isin(SELECTED)&~d.registration.isin(WAIVER)
    d["stopped"]=d.allocation.eq("停修")
    d["rejected"]=d.allocation.isin(WITHDRAWN)|d.registration.isin(WAIVER)
    d["score"]=pd.to_numeric(d.grade.where(d.grade.str.fullmatch(r"\d+(\.\d+)?")),errors="coerce")
    d["credit"]=pd.to_numeric(d.credits.where(d.credits.str.fullmatch(r"\d+(\.\d+)?")),errors="coerce")
    d["valid"]=d.selected&d.registration.eq("成績已輸入")&d.score.between(0,100)&d.credit.between(0,50)&~d.stopped
    d["valid_score"]=d.score.where(d.valid)
    d["numeric_score"]=d.score.where(d.score.between(0,100))
    keys=["student_key","department_code","course_code","term","offering_id"]
    g=d.groupby(keys,sort=False)
    a=g.agg(rows=("student_key","size"),selected=("selected","any"),rejected=("rejected","any"),
            stopped=("stopped","any"),valid=("valid","any"),score=("valid_score","max"),
            score_variants=("numeric_score","nunique"),credit_variants=("credit","nunique"),
            degree=("degree","first"),language=("language","first")).reset_index()
    a["conflict"]=(a.score_variants.gt(1)|a.credit_variants.gt(1)|
                   (a.selected&a.rejected)|(a.stopped&a.valid))
    a["state"]=np.select([a.conflict,a.stopped,a.valid&a.score.ge(60),a.valid&a.score.lt(60)],
                        ["衝突未知","停修","60分以上","未達60分"],default="其他成績未知")
    # Multiple sections selected for the same course-term are not arbitrarily picked.
    selected=a[a.selected].copy()
    k=["student_key","department_code","course_code","term"]
    t=selected.groupby(k,sort=False).agg(sections=("offering_id","nunique"),state=("state","first"),
             degree=("degree","first"),language=("language","first"),
             score=("score","first"),conflict=("conflict","any")).reset_index()
    multi=t.sections.gt(1)
    t.loc[multi,"state"]="衝突未知"
    t.loc[multi,"conflict"]=True
    t["order"]=t.term.map(order)
    return a,t,{"source_rows":len(d),"offering_attempts":len(a),
                "offering_attempts_with_multiple_source_rows":int(a.rows.gt(1).sum()),
                "conflicting_offering_attempts":int(a.conflict.sum()),
                "selected_course_terms_with_multiple_sections":int(multi.sum())}

def summarize(first):
    records=[]
    for (dept,code,period),p in first.groupby(["department_code","course_code","period"]):
        count=p.state.value_counts()
        n=len(p); known=int(p.state.isin(["60分以上","未達60分"]).sum())
        passed=int(count.get("60分以上",0));unknown=int(p.state.isin(["其他成績未知","衝突未知"]).sum())
        f=p[p.followup_ok]
        records.append(dict(department_code=dept,course_code=code,period=period,n=n,
            passed_60=passed,below_60=int(count.get("未達60分",0)),stopped=int(count.get("停修",0)),
            other_unknown=int(count.get("其他成績未知",0)),conflict_unknown=int(count.get("衝突未知",0)),
            passed_pct_all=100*passed/n,passed_pct_known=100*passed/known if known else np.nan,
            unknown_pct=100*unknown/n,calendar_and_visibility_followup_n=len(f),
            later_selection_4terms_n=int(f.repeat4.sum()),
            later_selection_4terms_pct=100*f.repeat4.mean() if len(f) else np.nan,
            first_visible_in_1051_n=int(p.term.eq("1051").sum())))
    return pd.DataFrame(records)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mysql",type=Path,default=DEFAULT_MYSQL)
    ap.add_argument("--login-path",default="codex-local")
    ap.add_argument("--database",default="ncu_course_flow_1150012")
    ap.add_argument("--candidates",type=Path,default=HERE/"outputs/language_conversion/candidate_courses.csv")
    ap.add_argument("--output-dir",type=Path,default=HERE/"outputs/conversion_first_attempt")
    args=ap.parse_args()
    query=lambda sql:frame(args.mysql,args.login_path,args.database,sql)
    c=pd.read_csv(args.candidates,dtype=str).fillna("")
    c=c[c.conversion_type.eq("全部轉英語")].copy()
    if c.duplicated(["department_code","course_code"]).any() if "department_code" in c else False:
        raise ValueError("Duplicate candidate keys")
    # Earlier inventory stores department name, not code. Resolve names conservatively.
    meta=query("""SELECT DISTINCT department_code,department_name,course_code
        FROM course_offerings WHERE term_code BETWEEN '1051' AND '1151'""")
    meta=meta.merge(c[["department","course_code"]],left_on=["department_name","course_code"],
                    right_on=["department","course_code"],how="inner").drop(columns="department")
    m=c.merge(meta,left_on=["department","course_code"],right_on=["department_name","course_code"],
              how="left",validate="one_to_one")
    if m.department_code.isna().any():raise ValueError("Unresolved candidate department")
    safe=lambda x:"'"+str(x).replace("'","''")+"'"
    pairs=" OR ".join(f"(o.department_code={safe(r.department_code)} AND o.course_code={safe(r.course_code)})"
                      for r in m.itertuples())
    print("Reading candidate-course source rows; no learner rows exported.",flush=True)
    raw=query(f"""SELECT er.student_key,o.department_code,o.course_code,o.offering_id,
        o.term_code term,o.teaching_language_raw language,COALESCE(st.degree_type_name,'') degree,
        r.grade,r.credits,r.allocation_result allocation,r.registration_attribute_name registration
        FROM course_offerings o JOIN enrollment_records er ON er.offering_id=o.offering_id
        JOIN student_course_grade_raw r ON r.grade_row_id=er.source_grade_row_id
        LEFT JOIN student_terms st ON st.student_key=er.student_key AND st.term_code=er.term_code
        WHERE ({pairs}) AND o.term_code BETWEEN '1051' AND '1142'
        AND o.offering_status_raw='正常'""")
    attempts,terms,audit=resolve(raw)
    first=terms.sort_values(["order"]).drop_duplicates(["student_key","department_code","course_code"]).copy()
    audit["first_observed_selected_before_degree_filter"]=len(first)
    # Select earliest in all observed records first, never skip an earlier unknown-degree attempt.
    first=first[first.degree.eq("大學")].copy()
    first=first.merge(m[["department_code","course_code","first_english_term"]],
                      on=["department_code","course_code"],validate="many_to_one")
    first["event_order"]=first.first_english_term.map(order)
    first["period"]=np.where(first.order<first.event_order,"轉換前","轉換後")
    # Only same seasonal offerings used by the conversion inventory.
    first=first[first.term.str[-1].eq(first.first_english_term.str[-1])].copy()
    first["language_expected"]=np.where(first.period.eq("轉換前"),"國語","英語")
    audit["unexpected_language_first_selections"]=int(first.language.ne(first.language_expected).sum())
    last=query("""SELECT student_key,MAX(term_code) last_term FROM student_terms
                  WHERE term_code BETWEEN '1051' AND '1142' GROUP BY student_key""")
    first=first.merge(last,on="student_key",how="left",validate="many_to_one")
    first["last_order"]=first.last_term.map(order)
    first["followup_ok"]=first.order.add(4).le(order("1142"))&first.last_order.ge(first.order+4)
    later=terms.groupby(["student_key","department_code","course_code"]).apply(
        lambda p: sorted(p.order.unique()),include_groups=False).to_dict()
    first["repeat4"]=[any(r.order<x<=r.order+4 for x in later[(r.student_key,r.department_code,r.course_code)])
                      for r in first.itertuples()]
    result=summarize(first).merge(m[["department_code","course_code","department","course_name","first_english_term"]],
                                  on=["department_code","course_code"],validate="many_to_one")
    # All output cells are course-period aggregates, never learner-level.
    args.output_dir.mkdir(parents=True,exist_ok=True)
    result.to_csv(args.output_dir/"first_selection_outcomes.csv",index=False,encoding="utf-8-sig")
    states=first.groupby(["period","state"]).size().unstack(fill_value=0)
    states.to_csv(args.output_dir/"overall_state_counts.csv",encoding="utf-8-sig")
    audit.update(candidate_courses=len(c),courses_with_first_selection_outcomes=int(result.course_code.nunique()),
        first_observed_undergraduate_course_selections=len(first),unique_learners=int(first.student_key.nunique()),
        cutoff="1142",pass_rule="numeric score >=60; proxy only, no official completion flag",
        followup_rule="four calendar semesters and a student-term record at or beyond window end; absence not proven no retake",
        repeat_rule="any later observed selected course-term in four semesters, including ambiguous later attempts; not proof of formal retake",
        unit="student x course first observed selection; same learner may appear in several courses",
        limits=["Not actual lifetime first attempt; left censoring from 1051",
                "Explicit same-term undergraduate only","No eight-semester requirement",
                "No required-student roster; cannot estimate delayed enrollment",
                "Course-grade proxy, not causal effect or learning quality",
                "Course-code changes and unmatched enrollments may hide earlier/later attempts",
                "Raw pre/post different cohorts and followup; not adjusted comparison"])
    (args.output_dir/"audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(audit,ensure_ascii=True),flush=True)
    print(states.to_string(),flush=True)

if __name__=="__main__":main()
