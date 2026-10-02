from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.services import chembl


class ChemblApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="chembl-researcher", password="test-password-123"
        )
        self.client.force_authenticate(self.user)

    @patch("apps.core.views.external_analysis.search_molecules")
    def test_molecule_query_requires_explicit_consent_and_sends_only_the_query(self, search):
        search.return_value = {
            "source": "ChEMBL",
            "sourceVersion": "ChEMBL_37",
            "releaseDate": "2026-05-01",
            "query": "quercetin",
            "endpoint": "https://www.ebi.ac.uk/chembl/api/data/molecule/search",
            "retrievedAt": "2026-10-03T09:00:00Z",
            "limit": 10,
            "results": [],
        }
        url = reverse("chembl-molecule-search")

        denied = self.client.post(url, {"query": "quercetin", "consent": False}, format="json")
        self.assertEqual(denied.status_code, 400)
        search.assert_not_called()

        response = self.client.post(url, {"query": " quercetin ", "consent": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["sourceVersion"], "ChEMBL_37")
        search.assert_called_once_with("quercetin")

    @patch("apps.core.views.external_analysis.search_molecules")
    def test_molecule_search_requires_authentication_and_caps_query_length(self, search):
        self.client.force_authenticate(None)
        response = self.client.post(
            reverse("chembl-molecule-search"), {"query": "quercetin", "consent": True}, format="json"
        )
        self.assertEqual(response.status_code, 401)
        self.client.force_authenticate(self.user)
        too_long = self.client.post(
            reverse("chembl-molecule-search"), {"query": "q" * 121, "consent": True}, format="json"
        )
        self.assertEqual(too_long.status_code, 400)
        search.assert_not_called()

    @patch("apps.core.views.external_analysis.molecule_activities")
    def test_activity_query_requires_consent_and_validates_chembl_id(self, activities):
        activities.return_value = {
            "source": "ChEMBL", "sourceVersion": "ChEMBL_37", "releaseDate": "2026-05-01",
            "chemblId": "CHEMBL50", "endpoint": "https://www.ebi.ac.uk/chembl/api/data/activity",
            "retrievedAt": "2026-10-03T09:00:00Z", "resultLimit": 50, "totalCount": 0,
            "truncated": False, "results": [],
        }
        url = reverse("chembl-activity-search")
        denied = self.client.post(url, {"chemblId": "CHEMBL50", "consent": False}, format="json")
        invalid = self.client.post(url, {"chemblId": "https://evil.example", "consent": True}, format="json")
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(invalid.status_code, 400)
        activities.assert_not_called()

        response = self.client.post(url, {"chemblId": "chembl50", "consent": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["chemblId"], "CHEMBL50")
        activities.assert_called_once_with("chembl50")


class ChemblServiceTests(SimpleTestCase):
    @patch("apps.core.services.chembl.timezone.now")
    @patch("apps.core.services.chembl._source_release")
    @patch("apps.core.services.chembl._request_json")
    def test_molecule_search_returns_bounded_records_and_version_provenance(self, request_json, source_release, now):
        now.return_value.isoformat.return_value = "2026-10-03T09:00:00+00:00"
        source_release.return_value = {"version": "ChEMBL_37", "releaseDate": "2026-05-01"}
        request_json.return_value = {"molecules": [{
            "molecule_chembl_id": "CHEMBL50", "pref_name": "Quercetin", "molecule_type": "Small molecule",
            "max_phase": "3.0", "first_approval": None, "natural_product": 1,
            "molecule_structures": {"canonical_smiles": "CO"},
            "molecule_properties": {"molfile": "must not be returned"},
        }]}

        result = chembl.search_molecules("quercetin")

        self.assertEqual(result["sourceVersion"], "ChEMBL_37")
        self.assertEqual(result["results"][0]["chemblId"], "CHEMBL50")
        self.assertEqual(result["results"][0]["preferredName"], "Quercetin")
        self.assertEqual(result["results"][0]["naturalProduct"], 1)
        self.assertEqual(result["resolvedQueries"], ["Quercetin"])
        self.assertNotIn("molfile", result["results"][0])
        request_json.assert_called_once_with("molecule/search.json", {
            "q": "Quercetin",
            "limit": "10",
            "only": "molecule_chembl_id,pref_name,molecule_type,max_phase,first_approval,natural_product,molecule_structures",
        })

    @patch("apps.core.services.chembl._source_release")
    @patch("apps.core.services.chembl._request_json")
    def test_chinese_component_name_uses_main_branch_english_alias_for_provider_query(self, request_json, source_release):
        source_release.return_value = {"version": "ChEMBL_37", "releaseDate": "2026-05-01"}
        request_json.return_value = {"molecules": [{
            "molecule_chembl_id": "CHEMBL50", "pref_name": "QUERCETIN", "natural_product": 1,
            "molecule_structures": {"canonical_smiles": "CO"},
        }]}

        result = chembl.search_molecules("槲皮素")

        self.assertEqual(result["queries"], ["槲皮素"])
        self.assertEqual(result["resolvedQueries"], ["Quercetin"])
        self.assertEqual(result["nameMatches"][0]["chinese"], "槲皮素")
        self.assertEqual(result["results"][0]["sourceQuery"], "Quercetin")
        self.assertEqual(result["results"][0]["componentLatin"], "Quercetinum")
        request_json.assert_called_once()
        self.assertEqual(request_json.call_args.args[1]["q"], "Quercetin")

    @patch("apps.core.services.chembl._source_release")
    @patch("apps.core.services.chembl._request_json")
    def test_ginsenoside_alias_expansion_is_bounded_to_main_branch_terms(self, request_json, source_release):
        source_release.return_value = {"version": "ChEMBL_37", "releaseDate": "2026-05-01"}
        request_json.return_value = {"molecules": []}

        result = chembl.search_molecules("人参总皂苷")

        self.assertEqual(result["queriedTerms"], 8)
        self.assertEqual(result["results"], [])
        self.assertEqual(request_json.call_count, 8)
        self.assertIn("Ginsenoside", result["resolvedQueries"])

    @patch("apps.core.services.chembl._source_release")
    @patch("apps.core.services.chembl._request_json")
    def test_activity_query_caps_rows_and_records_standardized_assay_fields(self, request_json, source_release):
        source_release.return_value = {"version": "ChEMBL_37", "releaseDate": "2026-05-01"}
        request_json.side_effect = [
            {
                "activities": [{
                    "activity_id": 59656, "standard_type": "IC50", "standard_relation": "=",
                    "standard_value": "32870.0", "standard_units": "nM", "pchembl_value": "4.48",
                    "target_chembl_id": "CHEMBL3081", "target_pref_name": "AKR1B1",
                    "assay_chembl_id": "CHEMBL647989", "assay_description": "Bovine lens assay",
                    "assay_type": "B", "document_chembl_id": "CHEMBL1132271",
                }],
                "page_meta": {"total_count": 1},
            },
            {
                "activities": [{
                    "activity_id": 59657, "standard_type": "Inhibition", "standard_relation": "=",
                    "standard_value": "73.0", "standard_units": "%", "pchembl_value": None,
                    "target_chembl_id": "CHEMBL3081", "target_pref_name": "AKR1B1",
                    "assay_chembl_id": "CHEMBL647988", "assay_description": "Bovine lens assay",
                    "assay_type": "B", "document_chembl_id": "CHEMBL1132271",
                }],
                "page_meta": {"total_count": 79},
            },
        ]

        result = chembl.molecule_activities("chembl50")

        self.assertEqual(result["chemblId"], "CHEMBL50")
        self.assertEqual(result["totalCount"], 80)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["results"][0]["standardType"], "IC50")
        self.assertEqual(result["results"][0]["targetId"], "CHEMBL3081")
        self.assertEqual(result["results"][1]["standardType"], "Inhibition")
        pchembl_params = request_json.call_args_list[0].args[1]
        standard_params = request_json.call_args_list[1].args[1]
        self.assertEqual(pchembl_params["molecule_chembl_id"], "CHEMBL50")
        self.assertEqual(pchembl_params["limit"], str(chembl.ACTIVITY_LIMIT))
        self.assertEqual(pchembl_params["pchembl_value__isnull"], "false")
        self.assertEqual(standard_params["standard_value__isnull"], "false")
        self.assertEqual(standard_params["pchembl_value__isnull"], "true")

    @patch("apps.core.services.chembl._source_release")
    @patch("apps.core.services.chembl._request_json")
    def test_activity_count_includes_standard_only_rows_after_result_cap(self, request_json, source_release):
        source_release.return_value = {"version": "ChEMBL_37", "releaseDate": "2026-05-01"}
        pchembl_rows = [{
            "activity_id": index + 1, "standard_type": "IC50", "standard_value": "1.0",
            "standard_units": "nM", "pchembl_value": "8.00",
        } for index in range(chembl.ACTIVITY_LIMIT)]
        request_json.side_effect = [
            {"activities": pchembl_rows, "page_meta": {"total_count": 846}},
            {"activities": [{"activity_id": 999, "standard_type": "Ki", "standard_value": "1.0"}],
             "page_meta": {"total_count": 1549}},
        ]

        result = chembl.molecule_activities("CHEMBL50")

        self.assertEqual(len(result["results"]), chembl.ACTIVITY_LIMIT)
        self.assertEqual(result["totalCount"], 2395)
        self.assertTrue(result["truncated"])
        self.assertEqual(request_json.call_args_list[1].args[1]["limit"], "1")

    @patch("apps.core.services.chembl._source_release")
    @patch("apps.core.services.chembl._request_json")
    def test_invalid_activity_identifier_never_calls_upstream(self, request_json, source_release):
        with self.assertRaises(ValueError):
            chembl.molecule_activities("https://example.invalid")
        source_release.assert_not_called()
        request_json.assert_not_called()
