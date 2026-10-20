from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.services.component_names import (
    compare_components_multilingual,
    normalize_name,
    resolve_component_names,
)


class ComponentNameResolutionTests(SimpleTestCase):
    def test_main_aliases_normalize_greek_letters_and_fullwidth_forms(self):
        resolution = resolve_component_names("β-谷甾醇；槲皮素")
        self.assertEqual([candidate["term"] for candidate in resolution["candidates"]], ["beta-sitosterol", "Quercetin"])
        self.assertEqual(normalize_name("β-sitosterol"), normalize_name("Beta-sitosterol"))
        self.assertEqual(normalize_name("Ginsenoside Ⅱ"), normalize_name("Ginsenoside II"))

    def test_query_term_limit_rejects_oversized_batches(self):
        with self.assertRaises(ValueError):
            resolve_component_names(",".join(f"compound-{index}" for index in range(13)))

    def test_ginsenoside_variants_are_reported_as_family_candidates_not_exact_matches(self):
        result = compare_components_multilingual("Ginsenoside Rg2", "Protopanaxadiol Rg2")
        self.assertEqual(result["counts"]["matched"], 0)
        self.assertEqual(result["counts"]["familyMatches"], 1)
        self.assertEqual(result["familyMatches"][0]["status"], "同家族候选")

    def test_chinese_english_and_latin_names_compare_as_one_exact_component(self):
        result = compare_components_multilingual("槲皮素; Quercetin", "Quercetinum、黄芩素")
        self.assertEqual(result["counts"]["detected"], 1)
        self.assertEqual(result["counts"]["reference"], 2)
        self.assertEqual(result["counts"]["matched"], 1)
        self.assertEqual(result["exactMatches"][0]["english"], "Quercetin")
        self.assertEqual(result["counts"]["matchRate"], 50.0)


class ComponentCompareApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="compare-owner", password="test-password-123")

    @patch("apps.core.views.external_analysis.compare_components_multilingual")
    def test_compare_requires_authentication_and_returns_local_result_without_external_provider(self, compare):
        compare.return_value = {"counts": {"detected": 1, "reference": 1, "matched": 1}}
        url = reverse("component-compare")
        denied = self.client.post(url, {"detected": "槲皮素", "reference": "Quercetin"}, format="json")
        self.assertEqual(denied.status_code, 401)
        self.client.force_authenticate(self.user)
        response = self.client.post(url, {"detected": "槲皮素", "reference": "Quercetin"}, format="json")
        self.assertEqual(response.status_code, 200)
        compare.assert_called_once_with("槲皮素", "Quercetin")

    def test_component_compare_rejects_empty_side(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            reverse("component-compare"), {"detected": "槲皮素", "reference": "  "}, format="json"
        )
        self.assertEqual(response.status_code, 400)
