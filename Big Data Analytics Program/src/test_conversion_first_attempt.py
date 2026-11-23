"""Synthetic-only checks; never reads school data."""
import unittest
import pandas as pd
from analyze_conversion_first_attempt import resolve, order

class OutcomeRules(unittest.TestCase):
    def row(self, **kwargs):
        base=dict(student_key="1",department_code="X",course_code="X1001",term="1101",
                  offering_id="1",degree="大學",language="國語",grade="80",credits="3",
                  allocation="中選(初選)",registration="成績已輸入")
        return base|kwargs

    def test_repeated_rows_do_not_create_repeat_attempt(self):
        a,t,_=resolve(pd.DataFrame([self.row(),self.row()]))
        self.assertEqual(len(t),1)
        self.assertEqual(t.iloc[0].state,"60分以上")

    def test_conflicting_scores_are_not_arbitrarily_selected(self):
        _,t,_=resolve(pd.DataFrame([self.row(),self.row(grade="40")]))
        self.assertEqual(t.iloc[0].state,"衝突未知")

    def test_stop_and_blank_score_are_separate(self):
        _,t,_=resolve(pd.DataFrame([self.row(grade="",allocation="停修",registration=""),
                                  self.row(student_key="2",grade="",registration="")]))
        self.assertEqual(set(t.state),{"停修","其他成績未知"})

    def test_withdrawal_conflict_and_multiple_sections(self):
        _,t,_=resolve(pd.DataFrame([self.row(),self.row(allocation="人工退選"),
                                  self.row(student_key="2"),
                                  self.row(student_key="2",offering_id="2")]))
        self.assertTrue(t.state.eq("衝突未知").all())

    def test_followup_calendar_order(self):
        self.assertEqual(order("1102")+1,order("1111"))
        self.assertEqual(order("1122")+4,order("1142"))

if __name__=="__main__":unittest.main()
