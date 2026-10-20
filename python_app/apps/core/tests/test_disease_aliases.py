from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import DataSource, KnowledgeEntity, SourceRelease
from apps.core.services.disease_names import expand_disease_queries


class DiseaseAliasExpansionTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="disease-alias-user", password="test-password-123")
        source = DataSource.objects.create(slug="disease-fixture", name="合成疾病来源")
        release = SourceRelease.objects.create(source=source, version="fixture-v1")
        disabled_source = DataSource.objects.create(
            slug="disease-disabled-fixture", name="停用疾病来源", enabled=False
        )
        disabled_release = SourceRelease.objects.create(source=disabled_source, version="fixture-v1")
        self.fibrosis = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.DISEASE,
            stable_id="EFO:0000768",
            label="肺纤维化",
            synonyms=["Pulmonary fibrosis", "Idiopathic pulmonary fibrosis"],
            source_release=release,
        )
        self.other = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.DISEASE,
            stable_id="DOID:0050156",
            label="冠状动脉粥样硬化",
            synonyms=["Coronary atherosclerosis"],
            source_release=release,
        )
        self.inactive = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.DISEASE,
            stable_id="inactive:fibrosis",
            label="Pulmonary fibrosis inactive",
            is_active=False,
            source_release=release,
        )
        self.disabled_source_disease = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.DISEASE,
            stable_id="disabled:EFO:0000768",
            label="Pulmonary fibrosis from disabled source",
            synonyms=["Pulmonary fibrosis"],
            source_release=disabled_release,
        )
        self.herb = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.HERB,
            stable_id="herb:pulmonary",
            label="Pulmonary herb",
            source_release=release,
        )

    def test_main_exact_chinese_aliases_expand_to_unique_english_terms(self):
        queries = expand_disease_queries("肺纤维化")
        self.assertEqual(queries[0], "肺纤维化")
        self.assertIn("Pulmonary fibrosis", queries)
        self.assertIn("Idiopathic pulmonary fibrosis", queries)
        self.assertEqual(len(queries), len(set(queries)))

    def test_unmapped_chinese_disease_does_not_receive_broad_token_guesses(self):
        self.assertEqual(expand_disease_queries("少见未知病名"), ["少见未知病名"])

    def test_alias_search_matches_only_active_local_diseases_and_labels_matched_terms(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(reverse("disease-alias-search"), {"query": "肺纤维化"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.fibrosis.pk)
        self.assertIn("Pulmonary fibrosis", response.data["results"][0]["matchedQueries"])
        self.assertIn("Idiopathic pulmonary fibrosis", response.data["results"][0]["matchedQueries"])
        self.assertEqual(response.data["aliasSourceCommit"], "078d374")
        self.assertNotIn(self.inactive.pk, {row["id"] for row in response.data["results"]})
        self.assertNotIn(self.disabled_source_disease.pk, {row["id"] for row in response.data["results"]})
        self.assertNotIn(self.herb.pk, {row["id"] for row in response.data["results"]})
        self.assertNotIn(self.other.pk, {row["id"] for row in response.data["results"]})

    def test_alias_search_requires_auth_and_rejects_blank_or_unbounded_queries(self):
        url = reverse("disease-alias-search")
        self.assertEqual(self.client.get(url, {"query": "肺纤维化"}).status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(url, {"query": "   "}).status_code, 400)
        self.assertEqual(self.client.get(url, {"query": "肺" * 121}).status_code, 400)
