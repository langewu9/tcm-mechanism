from django.test import SimpleTestCase

from apps.proteomics.services import _parse_rows, resolve_mapping


class InvalidStatisticsTests(SimpleTestCase):
    def analyze(self, p=".01", fdr=".01"):
        rows = [{"Gene": "TP53", "log2FC": "2", "PValue": p, "FDR": fdr}]
        result, qc = _parse_rows(rows, resolve_mapping(list(rows[0]), {}), {"log2FcMin": 1, "fdrMax": .05, "pValueMax": .05})
        return result[0], qc

    def test_invalid_fdr_cannot_fall_back_to_a_valid_p_value(self):
        for value in ["-.1", "1.1", "malformed", "Infinity"]:
            with self.subTest(fdr=value):
                row, qc = self.analyze(fdr=value)
                self.assertFalse(row.selected)
                self.assertIn("invalid_numeric_value", row.exclusion_reasons)
                self.assertIn("invalid_fdr", row.qc_warnings)
                self.assertEqual(qc["invalidNumericValueRowCount"], 1)

    def test_invalid_p_value_is_not_hidden_by_valid_fdr(self):
        row, _ = self.analyze(p="1.1")
        self.assertFalse(row.selected)
        self.assertIn("invalid_p_value", row.qc_warnings)

    def test_missing_optional_statistic_keeps_valid_fallback_rules(self):
        self.assertTrue(self.analyze(fdr="")[0].selected)
        self.assertTrue(self.analyze(p="")[0].selected)

    def test_valid_fdr_retains_precedence_over_nonsignificant_valid_p(self):
        row, _ = self.analyze(p=".9", fdr=".01")
        self.assertTrue(row.selected)
