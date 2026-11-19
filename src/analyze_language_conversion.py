"""Read-only conversion screening. Aggregate exports only; T uses fixed pre-conversion reference."""
import json
from pathlib import Path
import pandas as pd
import numpy as np
from english_taught_analysis import DEFAULT_MYSQL, HERE, frame, SELECTED

OUT = HERE / "outputs/language_conversion"

def query(sql):
    return frame(DEFAULT_MYSQL, "codex-local", "ncu_course_flow_1150012", sql)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    o = query("""
        SELECT o.offering_id,o.term_code,o.course_code,o.course_name,
               o.department_code,o.department_name,o.course_attribute_raw,
               o.teaching_language_raw,r.degree_level_name,r.instructors,
               r.instructor_count,r.offering_grade_level,r.grading_method
        FROM course_offerings o JOIN course_offering_raw r
          ON r.offering_row_id=o.offering_id
        WHERE o.term_code BETWEEN '1051' AND '1151'
          AND o.offering_status_raw='正常'
    """).fillna("")
    print("offering rows",len(o),flush=True)
    candidate_ids=[]
    for _,p in o.groupby(["department_code","course_code"]):
        if (p.teaching_language_raw.eq("英語").any() and
            p.teaching_language_raw.eq("國語").any() and
            p.course_attribute_raw.str.contains("必修").all() and
            p.degree_level_name.eq("學士班").all()):
            candidate_ids.extend(p.offering_id.tolist())
    ids=",".join(str(int(x)) for x in candidate_ids) or "-1"
    print("candidate offering rows",len(candidate_ids),flush=True)
    selected=",".join("'"+x+"'" for x in sorted(SELECTED))
    # Distinct learner-offering rows prevent exact repeated imports from inflating counts.
    g=query(f"""
        SELECT offering_id,COUNT(*) n,AVG(score) mean_grade,
          STDDEV_SAMP(score) sd_grade,MIN(credits) min_credits,MAX(credits) max_credits,
          SUM(score) sum_grade,SUM(score*score) sumsq_grade
        FROM (
          SELECT DISTINCT er.offering_id,er.student_key,
            CAST(TRIM(r.grade) AS DECIMAL(10,3)) score,
            CAST(NULLIF(TRIM(r.credits),'') AS DECIMAL(10,3)) credits
          FROM enrollment_records er
          JOIN student_course_grade_raw r ON r.grade_row_id=er.source_grade_row_id
          JOIN student_terms st ON st.student_key=er.student_key AND st.term_code=er.term_code
          WHERE er.term_code BETWEEN '1051' AND '1142'
            AND er.offering_id IN ({ids})
            AND st.degree_type_name='大學'
            AND TRIM(r.allocation_result) IN ({selected})
            AND TRIM(r.grade) REGEXP '^[0-9]+([.][0-9]+)?$'
            AND CAST(TRIM(r.grade) AS DECIMAL(10,3)) BETWEEN 0 AND 100
        ) x GROUP BY offering_id
    """)
    for c in g.columns:
        if c!="offering_id":g[c]=pd.to_numeric(g[c],errors="coerce")
    o=o.merge(g,on="offering_id",how="left")
    o["order"]=o.term_code.str[:3].astype(int)*2+o.term_code.str[-1].astype(int)
    o["english"]=o.teaching_language_raw.eq("英語")
    o["mandarin"]=o.teaching_language_raw.eq("國語")
    rows=[]; history=[]
    for (dept,code),p in o.groupby(["department_code","course_code"]):
        if not code or code.startswith("LN") or not p.degree_level_name.eq("學士班").all():continue
        if not p.course_attribute_raw.str.contains("必修").all():continue
        if p.course_name.nunique()!=1 or not p.english.any() or not p.mandarin.any():continue
        if not (p.english|p.mandarin).all():continue
        t=p.loc[p.english,"order"].min()
        pre=p[p.order<t]; post=p[p.order>=t]
        # Same calendar semester ensures annual fall/spring scheduling does not mimic change.
        sem=p.loc[p.order.eq(t),"term_code"].iloc[0][-1]
        before=pre[pre.term_code.str.endswith(sem)]
        after=post[post.term_code.str.endswith(sem)]
        if before.term_code.nunique()<2 or after.term_code.nunique()<2:continue
        if not after.groupby("term_code").english.any().all():continue
        npre=before.n.sum(); npost=after.loc[after.english,"n"].sum()
        if npre<30 or npost<30:continue
        if before.loc[before.n.gt(0),"term_code"].nunique()<2:continue
        if after.loc[after.english & after.n.gt(0),"term_code"].nunique()<2:continue
        credits=p.loc[p.n.gt(0),["min_credits","max_credits"]].stack().dropna().unique()
        preteachers=set(before.loc[before.instructor_count.eq("1"),"instructors"])-{""}
        postteachers=set(after.loc[after.english & after.instructor_count.eq("1"),"instructors"])-{""}
        common=preteachers & postteachers
        before=before[before.n.gt(0)]
        nn=before.n.sum(); mu=before.sum_grade.sum()/nn
        sd=np.sqrt(max(0,(before.sumsq_grade.sum()-nn*mu*mu)/(nn-1))) if nn>1 else np.nan
        for z in p.itertuples():
            history.append({"department":p.department_name.iloc[0],"course_code":code,"course_name":z.course_name,
                "term":z.term_code,"language":z.teaching_language_raw,"attribute":z.course_attribute_raw,
                "instructors":z.instructors,"instructor_count":z.instructor_count,"n":z.n,
                "mean_grade":z.mean_grade,"sd_grade":z.sd_grade,
                "min_credits":z.min_credits,"max_credits":z.max_credits,
                "fixed_reference_t_mean":50+10*(z.mean_grade-mu)/sd if sd>0 else np.nan,
                "reference_mean":mu,"reference_sd":sd,
                "reference_rule":"pre-first-English same-calendar-semester Mandarin grade pool"})
        eng=after[after.english & after.n.gt(0)]
        postmu=eng.sum_grade.sum()/eng.n.sum()
        rows.append({"department":p.department_name.iloc[0],"course_code":code,"course_name":p.course_name.iloc[0],
            "first_english_term":p.loc[p.order.eq(t),"term_code"].iloc[0],
            "conversion_type":"全部轉英語" if after.english.all() else "中英並行或部分轉換",
            "pre_same_season_terms":before.term_code.nunique(),"post_same_season_terms":after.term_code.nunique(),
            "pre_numeric_grade_rows":int(nn),"post_english_numeric_grade_rows":int(eng.n.sum()),
            "stable_credit":len(credits)==1,"credit_values":"|".join(map(str,sorted(credits))),
            "shared_solo_teachers":len(common),"shared_teacher_names":"|".join(sorted(common)),
            "pre_mean":mu,"post_english_mean":postmu,"reference_sd":sd,
            "post_fixed_t_mean":50+10*(postmu-mu)/sd if sd>0 else np.nan})
    result=pd.DataFrame(rows)
    if len(result):
        result=result.sort_values(["stable_credit","shared_solo_teachers","post_english_numeric_grade_rows"],ascending=False)
    result.to_csv(OUT/"candidate_courses.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(history).to_csv(OUT/"candidate_offering_history.csv",index=False,encoding="utf-8-sig")
    summary={"screened_candidates":len(result),"strict_candidates":int((result.stable_credit & result.shared_solo_teachers.gt(0) & result.conversion_type.eq("全部轉英語")).sum()) if len(result) else 0,
      "grade_scope":"Explicit same-term 大學 label; selected; numeric 0..100; 1051..1142; exact duplicate learner-offering-score-credit rows removed",
      "limits":["Same name/code does not establish syllabus identity","Course mandatory label does not establish every student's required curriculum","1151 grades excluded","Fixed-reference T is grade rescaling, not common assessment or causal learning effect","Conflicting non-identical duplicate scores are not resolved by exact deduplication"]}
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    print(result.head(12).to_string(index=False),flush=True)

if __name__=="__main__":main()
