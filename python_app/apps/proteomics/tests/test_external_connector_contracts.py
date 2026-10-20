"""Offline error-boundary tests for main's MyGene/Reactome integrations."""

import copy
import io
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.test import SimpleTestCase, TestCase

from apps.proteomics import external_reactome
from apps.proteomics.integrations import run_opt_in_reactome
from apps.proteomics.models import ProteomicsRowResult


def valid_payload():
    return {
        "summary": {"token": "fixture-token"},
        "pathways": [{
            "stId": "R-HSA-1", "name": "合成人类通路", "species": {"name": "Homo sapiens"},
            "entities": {"found": 3, "total": 10, "ratio": 0.3, "pValue": 0.001, "fdr": 0.02},
        }],
        "identifiersNotFound": 0, "pathwaysFound": 1,
    }


class ExternalTransportContractTests(SimpleTestCase):
    @patch("apps.proteomics.external_reactome.build_opener")
    def test_selected_identifiers_are_posted_only_to_main_endpoint_and_redirects_are_refused(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b'{"pathways":[]}'

        status, body = external_reactome._request_bytes(
            external_reactome.REACTOME_ANALYSIS_URL, data=b"TP53\nIL6", content_type="text/plain", timeout=45,
        )

        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, external_reactome.REACTOME_ANALYSIS_URL)
        self.assertEqual(request.data, b"TP53\nIL6")
        self.assertEqual(request.method, "POST")
        self.assertEqual(opener.call_args.args, (external_reactome._NoRedirect,))
        self.assertIsNone(external_reactome._NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid"))
        response.read.assert_called_once_with(external_reactome.MAX_RESPONSE_BYTES + 1)
        self.assertEqual((status, body), (200, b'{"pathways":[]}'))

    @patch("apps.proteomics.external_reactome.build_opener")
    def test_oversized_response_is_rejected_after_bounded_read(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b"x" * 129
        with self.assertRaisesRegex(external_reactome.ExternalEnrichmentError, "大小限制"):
            external_reactome._request_bytes(external_reactome.MYGENE_QUERY_URL, max_bytes=128)
        response.read.assert_called_once_with(129)

    @patch("apps.proteomics.external_reactome.build_opener")
    def test_provider_status_timeout_and_redirect_errors_do_not_expose_body(self, opener):
        for failure in (
            HTTPError(external_reactome.MYGENE_QUERY_URL, 302, "redirect", {}, io.BytesIO(b"PRIVATE_PROVIDER_BODY")),
            HTTPError(external_reactome.MYGENE_QUERY_URL, 503, "down", {}, io.BytesIO(b"PRIVATE_PROVIDER_BODY")),
            URLError("PRIVATE_PROVIDER_BODY"), TimeoutError("PRIVATE_PROVIDER_BODY"),
        ):
            with self.subTest(failure=type(failure).__name__):
                opener.return_value.open.side_effect = failure
                with self.assertRaises(external_reactome.ExternalEnrichmentError) as error:
                    external_reactome._request_json(external_reactome.MYGENE_QUERY_URL)
                self.assertNotIn("PRIVATE_PROVIDER_BODY", str(error.exception))


class ReactomeResponseContractTests(SimpleTestCase):
    @patch("apps.proteomics.external_reactome._request_bytes", return_value=(200, b"94"))
    @patch("apps.proteomics.external_reactome._request_json")
    def test_invalid_statistics_do_not_become_significant_or_empty_success(self, request_json, request_bytes):
        for field, value in (("found", 2.5), ("found", True), ("fdr", -0.01), ("fdr", 1.2), ("fdr", None), ("total", 2), ("pValue", "bad"), ("ratio", 1.1)):
            payload = valid_payload()
            payload["pathways"][0]["entities"][field] = value
            request_json.return_value = payload
            with self.subTest(field=field, value=value), self.assertRaises(external_reactome.ExternalEnrichmentError):
                external_reactome.analyze_reactome_human_pathways(["TP53", "IL6"])
        request_bytes.assert_not_called()

    @patch("apps.proteomics.external_reactome._request_json")
    def test_invalid_pathway_identity_is_not_stringified_into_evidence(self, request_json):
        for field, value in (("stId", {}), ("name", []), ("entities", None)):
            payload = valid_payload()
            payload["pathways"][0][field] = value
            request_json.return_value = payload
            with self.subTest(field=field), self.assertRaises(external_reactome.ExternalEnrichmentError):
                external_reactome.analyze_reactome_human_pathways(["TP53", "IL6"])

    @patch("apps.proteomics.external_reactome._request_bytes", return_value=(200, b"94"))
    @patch("apps.proteomics.external_reactome._request_json")
    def test_invalid_pathway_summary_and_species_shapes_are_not_empty_success(self, request_json, request_bytes):
        invalid = [{}, {"pathways": None}, {"pathways": {}}, {"pathways": [], "summary": []}, {"pathways": [], "summary": {"token": {}}}]
        wrong_species = valid_payload()
        wrong_species["pathways"][0]["species"] = ["Homo sapiens"]
        invalid.append(wrong_species)
        for payload in invalid:
            with self.subTest(payload=payload):
                request_json.return_value = payload
                with self.assertRaises(external_reactome.ExternalEnrichmentError):
                    external_reactome.analyze_reactome_human_pathways(["TP53", "IL6"])
        request_bytes.assert_not_called()

    @patch("apps.proteomics.external_reactome._request_bytes")
    @patch("apps.proteomics.external_reactome._request_json", side_effect=lambda *a, **k: valid_payload())
    def test_optional_version_failure_keeps_human_pathways_with_unknown_version(self, request_json, request_bytes):
        for version_response in ((200, b"\xff"), (503, b"not available")):
            with self.subTest(version_response=version_response):
                request_bytes.return_value = version_response
                result = external_reactome.analyze_reactome_human_pathways(["TP53", "IL6"])
                self.assertIsNone(result["sourceVersion"])
                self.assertEqual(len(result["pathways"]), 1)
                self.assertEqual(result["token"], "fixture-token")
                self.assertEqual(request_bytes.call_args.kwargs["max_bytes"], 4096)

    @patch("apps.proteomics.external_reactome._request_bytes", return_value=(200, b"94"))
    @patch("apps.proteomics.external_reactome._request_json")
    def test_actual_empty_pathway_array_and_optional_species_remain_supported(self, request_json, request_bytes):
        request_json.return_value = {"pathways": []}
        empty = external_reactome.analyze_reactome_human_pathways(["TP53", "IL6"])
        self.assertEqual(empty["pathways"], [])
        self.assertIsNone(empty["token"])

        payload = valid_payload()
        payload["pathways"][0].pop("species")
        mouse = copy.deepcopy(payload["pathways"][0])
        mouse.update({"stId": "R-MMU-1", "species": {"name": "Mus musculus"}})
        payload["pathways"].append(mouse)
        request_json.return_value = payload
        result = external_reactome.analyze_reactome_human_pathways(["TP53", "IL6"])
        self.assertEqual([item["stableId"] for item in result["pathways"]], ["R-HSA-1"])
        self.assertEqual(result["pathways"][0]["species"], "Homo sapiens")


class ExternalFailureRetentionTests(TestCase):
    @patch("apps.proteomics.external_reactome._request_json", return_value={"pathways": None})
    def test_invalid_external_response_preserves_successful_local_proteomics_data(self, request_json):
        row = SimpleNamespace(
            selected=True, original_label="TP53", normalized_symbol="TP53", row_index=1,
            mapping_status=ProteomicsRowResult.MappingStatus.DATABASE, mapping_source="fixture-local:v1", external_identifiers=[],
        )
        result = {"rows": [{"index": 1, "selected": True}], "summary": {"selectedCount": 1}, "validation": {"referenceTargets": ["TP53"]}}

        releases, warnings = run_opt_in_reactome(None, result, [row])

        self.assertEqual(releases, [])
        self.assertEqual(result["summary"]["selectedCount"], 1)
        self.assertEqual(result["rows"][0]["symbol"], "TP53")
        self.assertEqual(result["externalReactome"]["status"], "unavailable")
        self.assertEqual(result["externalReactome"]["failureStage"], "reactome_enrichment")
        self.assertIn("已保留本地分析", warnings[0])
        self.assertEqual(request_json.call_args.kwargs["data"], b"TP53")
