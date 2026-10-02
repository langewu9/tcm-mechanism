from unittest.mock import patch

from django.test import SimpleTestCase

from apps.proteomics.external_gprofiler import (
    GPROFILER_PROFILE_URL,
    GPROFILER_SOURCES,
    GPROFILER_VERSIONS_URL,
    analyze_human_go_kegg,
)


class GProfilerAnalysisTests(SimpleTestCase):
    @patch("apps.proteomics.external_gprofiler._read_json")
    def test_go_kegg_uses_human_custom_background_and_fdr(self, request_json):
        request_json.side_effect = [
            {
                "gprofiler_version": "e114_eg62_p19_test",
                "sources": {"GO:BP": {"version": "2026-03"}, "KEGG": {"version": "2026-02"}},
            },
            {
                "meta": {"query_metadata": "captured"},
                "result": [
                    {
                        "native": "GO:0001234",
                        "name": "Example biological process",
                        "source": "GO:BP",
                        "p_value": 0.012,
                        "intersection_size": 2,
                        "query_size": 3,
                        "term_size": 7,
                        "effective_domain_size": 1000,
                        "precision": 2 / 3,
                        "recall": 2 / 7,
                        "intersections": [["ENSG000001", "ENSG000002"]],
                    },
                    {"native": "HSA00001", "name": "unrequested", "source": "REAC", "p_value": 0.001},
                ],
            },
        ]

        result = analyze_human_go_kegg(["TP53", "IL6", "TP53"], ["TP53", "IL6", "MAPK1"])

        self.assertEqual(request_json.call_args_list[0].args[0], GPROFILER_VERSIONS_URL)
        self.assertEqual(request_json.call_args_list[1].args[0], GPROFILER_PROFILE_URL)
        payload = request_json.call_args_list[1].kwargs["payload"]
        self.assertEqual(payload["organism"], "hsapiens")
        self.assertEqual(payload["sources"], list(GPROFILER_SOURCES))
        self.assertEqual(payload["domain_scope"], "custom")
        self.assertEqual(payload["query"], ["TP53", "IL6"])
        self.assertEqual(payload["background"], ["TP53", "IL6", "MAPK1"])
        self.assertEqual(payload["significance_threshold_method"], "fdr")
        self.assertEqual(result["sourceVersion"], "e114_eg62_p19_test:{\"GO:BP\":{\"version\":\"2026-03\"},\"KEGG\":{\"version\":\"2026-02\"}}")
        self.assertEqual(result["dataVersions"]["sources"]["KEGG"]["version"], "2026-02")
        self.assertEqual(result["terms"][0]["adjustedPValue"], 0.012)
        self.assertIsNone(result["terms"][0]["pValue"])
        self.assertEqual(result["terms"][0]["matchedIdentifiers"], ["ENSG000001", "ENSG000002"])
        self.assertEqual(len(result["terms"]), 1)

    @patch("apps.proteomics.external_gprofiler._read_json")
    def test_rejects_empty_query_and_oversized_background_before_network_call(self, request_json):
        with self.assertRaises(ValueError):
            analyze_human_go_kegg(["TP53"], ["TP53"])
        with self.assertRaises(ValueError):
            analyze_human_go_kegg(["TP53", "IL6"], [f"GENE{i}" for i in range(25_001)])
        request_json.assert_not_called()

    @patch("apps.proteomics.external_gprofiler.build_opener")
    def test_external_requests_refuse_redirects(self, opener):
        from apps.proteomics.external_gprofiler import _read_json, _NoRedirect

        opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"ok":true}'
        self.assertEqual(_read_json("https://biit.cs.ut.ee/example"), {"ok": True})
        opener.assert_called_once()
        self.assertIs(opener.call_args.args[0], _NoRedirect)
