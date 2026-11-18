import unittest

from apps.core.services.case_analysis_figures import build_case_figures, prescription_herbs


class CaseAnalysisFigureTests(unittest.TestCase):
    def test_explicit_doses_preserve_preparations_and_shared_doses(self):
        self.assertEqual(prescription_herbs("炙甘草6g，生石膏、知母各15g，砂仁后下6g。"),
                         ["炙甘草", "生石膏", "知母", "砂仁"])
        self.assertEqual(prescription_herbs("未提及"), [])
        self.assertEqual(prescription_herbs("前方去桃仁，加葛根。"), [])

    def test_missing_prescription_stays_in_rule_denominator(self):
        records = [{"herbs": herbs, "formulas": []} for herbs in (["甘草", "黄芩"], ["甘草"], [])]
        result = build_case_figures(records, "诊次")
        rows = result["figures"]["case_association_network"]["table"]["rows"]
        forward = next(row for row in rows if row[:2] == ["甘草", "黄芩"])
        reverse = next(row for row in rows if row[:2] == ["黄芩", "甘草"])
        self.assertAlmostEqual(forward[3], 1 / 3)
        self.assertEqual(forward[4], .5)
        self.assertEqual(reverse[4], 1)
        self.assertAlmostEqual(forward[5], 1.5)
        self.assertEqual(result["medicationSummary"]["missingPrescriptionCount"], 1)

    def test_no_drug_data_produces_no_fabricated_network_or_cluster(self):
        result = build_case_figures([{"herbs": [], "formulas": []}], "诊次")
        self.assertEqual(result["figures"], {})
        self.assertEqual(result["metrics"]["herbs"]["rows"], [])

    def test_private_row_identity_never_enters_figure_inputs(self):
        record = {"herbs": ["黄芩", "丹参", "甘草"], "formulas": [],
                  "case_group": "PRIVATE_CASE", "name": "PRIVATE_NAME", "narrative": "PRIVATE_NARRATIVE"}
        result = build_case_figures([record], "诊次")
        self.assertNotIn("PRIVATE_", str(result))
        self.assertNotIn("case_cluster_elbow", result["figures"])
        heat = result["figures"]["case_herb_pairs_heatmap"]["payload"]["data"]
        self.assertTrue(all(row["value"] == 1 for row in heat))


if __name__ == "__main__":
    unittest.main()
