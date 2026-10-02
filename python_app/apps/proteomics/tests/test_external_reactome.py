from unittest.mock import patch

from django.test import SimpleTestCase

from apps.proteomics.external_reactome import (
    analyze_reactome_human_pathways,
    resolve_human_identifiers,
)


class ExternalIdentifierTests(SimpleTestCase):
    @patch("apps.proteomics.external_reactome._request_json")
    def test_mygene_query_is_limited_to_human_and_keeps_ambiguous_ids_unresolved(self, request_json):
        request_json.return_value = [
            {
                "query": "p53",
                "symbol": "TP53",
                "name": "tumor protein p53",
                "entrezgene": 7157,
                "taxid": 9606,
            },
            {"query": "ambiguous", "symbol": "GENEA", "taxid": 9606},
            {"query": "ambiguous", "symbol": "GENEB", "taxid": 9606},
            {"query": "wrong-species", "symbol": "Trp53", "taxid": 10090},
        ]

        result = resolve_human_identifiers(["P53", "ambiguous", "wrong-species", "x" * 130])

        self.assertEqual(result["mappings"][0]["symbol"], "TP53")
        self.assertEqual(result["ambiguous"], ["ambiguous"])
        self.assertEqual(result["unmapped"], ["wrong-species"])
        self.assertEqual(result["rejected"], ["x" * 130])
        self.assertEqual(result["rejectedCount"], 1)
        request_args = request_json.call_args.args
        self.assertEqual(request_args[0], "https://mygene.info/v3/query")
        encoded_form = request_json.call_args.kwargs["data"].decode("utf-8")
        self.assertIn("species=human", encoded_form)
        self.assertIn("scopes=symbol%2Calias%2Cname", encoded_form)
        self.assertNotIn("x" * 130, encoded_form)


class ReactomeAnalysisTests(SimpleTestCase):
    @patch("apps.proteomics.external_reactome._request_bytes")
    @patch("apps.proteomics.external_reactome._request_json")
    def test_reactome_uses_projection_and_filters_by_fdr_and_minimum_hits(self, request_json, request_bytes):
        request_json.return_value = {
            "summary": {"token": "opaque-token"},
            "identifiersNotFound": 1,
            "pathwaysFound": 3,
            "pathways": [
                {
                    "stId": "R-HSA-1",
                    "name": "Significant pathway",
                    "species": {"name": "Homo sapiens"},
                    "entities": {"found": 3, "total": 10, "ratio": 0.3, "pValue": 0.001, "fdr": 0.02},
                },
                {
                    "stId": "R-HSA-2",
                    "name": "High FDR pathway",
                    "entities": {"found": 3, "total": 10, "ratio": 0.3, "pValue": 0.2, "fdr": 0.2},
                },
                {
                    "stId": "R-HSA-3",
                    "name": "Single hit pathway",
                    "entities": {"found": 1, "total": 10, "ratio": 0.1, "pValue": 0.001, "fdr": 0.01},
                },
            ],
        }
        request_bytes.return_value = (200, b"94")

        result = analyze_reactome_human_pathways(["TP53", "IL6", "TP53"])

        self.assertEqual(result["sourceVersion"], "94")
        self.assertEqual(result["token"], "opaque-token")
        self.assertEqual(result["submittedIdentifierCount"], 2)
        self.assertEqual([item["stableId"] for item in result["pathways"]], ["R-HSA-1"])
        self.assertEqual(request_json.call_args.args[0], "https://reactome.org/AnalysisService/identifiers/projection/?pageSize=100&page=1")
        self.assertEqual(request_json.call_args.kwargs["data"], b"TP53\nIL6")
        self.assertEqual(request_bytes.call_args.args[0], "https://reactome.org/ContentService/data/database/version")
