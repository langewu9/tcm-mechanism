from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.core.models import DataSource, KnowledgeEntity, SourceEntityMapping, SourceRelease


class CatalogDirectoryNameTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="directory-name-audit")
        self.client.force_authenticate(self.user)
        self.source = DataSource.objects.create(slug="directory-fixture", name="Synthetic directory fixture", enabled=True)
        self.release = SourceRelease.objects.create(source=self.source, version="fixture-v1", published_at=timezone.now())
        self.url = reverse("entity-list")

    def entity(self, key, label, kind="compound", **extra):
        return KnowledgeEntity.objects.create(entity_type=kind, stable_id=key, label=label, source_release=self.release, **extra)

    def search(self, query, kind="compound", **params):
        response = self.client.get(self.url, {"search": query, "entity_type": kind, **params})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_known_chinese_compound_matches_directory_and_all_types(self):
        acid = self.entity("compound:acid", "Glycyrrhizic acid")
        synonym = self.entity("compound:synonym", "Glycyrrhizin")
        self.entity("compound:salt", "Glycyrrhizic acid ammonium salt")
        for kind in ["compound", ""]:
            result = self.search("甘草酸", kind)
            self.assertEqual({row["id"] for row in result["results"]}, {acid.pk, synonym.pk})
            self.assertEqual(result["count"], 2)
        self.assertEqual(self.search("甘草酸", "herb")["count"], 0)

    def test_observed_alias_respects_source_visibility_and_publication(self):
        canonical = self.entity("compound:canonical", "Canonical fixture")
        SourceEntityMapping.objects.create(source_release=self.release, source_entity_id="c1", source_label="自定义中文别名",
            entity_type="compound", namespace="fixture", entity=canonical, status="mapped", metadata={})
        self.assertEqual(self.search("自定义中文别名")["count"], 1)
        self.release.published_at = None
        self.release.save(update_fields=["published_at"])
        self.assertEqual(self.search("自定义中文别名")["count"], 0)
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        self.assertEqual(self.search("Canonical fixture")["count"], 0)

    def test_herb_source_alias_and_exact_molecule_id_are_retrievable(self):
        herb = self.entity('herb:catalog', '麦冬', 'herb')
        SourceEntityMapping.objects.create(source_release=self.release, source_entity_id='pinyin:maidong',
            source_label='MAI DONG', entity_type='herb', namespace='batman.name.pinyin', entity=herb, status='mapped')
        self.assertEqual(self.search('mai dong', 'herb')['results'][0]['id'], herb.pk)
        compound = self.entity('compound:catalog', 'Named molecule')
        SourceEntityMapping.objects.create(source_release=self.release, source_entity_id='MOL010127',
            source_label=compound.label, entity_type='compound', namespace='tcmsp.mol_id', entity=compound, status='mapped')
        self.assertEqual(self.search('MOL010127', 'compound')['results'][0]['id'], compound.pk)
        self.assertEqual(self.search('MOL010127', 'herb')['count'], 0)

    def test_substring_and_stable_identifier_search_are_preserved(self):
        entity = self.entity("compound:unique-identifier", "Unlisted Synthetic Molecule")
        self.assertEqual(self.search("Synthetic")["results"][0]["id"], entity.pk)
        self.assertEqual(self.search("unique-identifier")["results"][0]["id"], entity.pk)
        self.assertEqual(self.search("NOT_FOUND_20261027")["count"], 0)

    def test_alias_pagination_has_unique_records_and_correct_total(self):
        for i in range(55): self.entity(f"compound:{i}", "Glycyrrhizic acid")
        first, second = self.search("甘草酸"), self.search("甘草酸", page=2)
        self.assertEqual((first["count"], second["count"]), (55,55))
        self.assertEqual((len(first["results"]), len(second["results"])), (50,5))
        self.assertFalse({row["id"] for row in first["results"]} & {row["id"] for row in second["results"]})

    def test_inactive_entities_and_unauthenticated_requests_stay_hidden(self):
        self.entity("compound:inactive", "Glycyrrhizic acid", is_active=False)
        self.assertEqual(self.search("甘草酸")["count"], 0)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.url,{"search":"甘草酸"}).status_code, 401)
