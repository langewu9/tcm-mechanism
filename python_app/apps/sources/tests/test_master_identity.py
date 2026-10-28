from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from apps.core.models import CanonicalIdentifier, DataSource, EntityIdentifier, KnowledgeEntity, SourceEntityMapping, SourceRecord, SourceRelease
from apps.sources.master_identity import bootstrap_existing_master_ids, preserve_source_record, resolve_source_identity

class MasterIdentityTests(TestCase):
    def setUp(self):
        self.a = DataSource.objects.create(slug='master-a', name='A', access_mode='download')
        self.b = DataSource.objects.create(slug='master-b', name='B', access_mode='download')
        self.ra = SourceRelease.objects.create(source=self.a, version='v1')
        self.rb = SourceRelease.objects.create(source=self.b, version='v1')

    def resolve(self, release=None, **kwargs):
        params = {'entity_type': 'protein', 'namespace': 'uniprot', 'identifier': 'P04637', 'label': 'TP53', 'taxon_key': '9606', **kwargs}
        return resolve_source_identity(release=release or self.ra, **params)

    def test_same_strong_identifier_shares_master_across_sources(self):
        a, b = self.resolve(), self.resolve(self.rb, label='Cellular tumor antigen p53')
        self.assertEqual(a.entity_id, b.entity_id)
        self.assertEqual(a.entity.canonical_id, b.entity.canonical_id)
        self.assertEqual(CanonicalIdentifier.objects.count(), 1)
        self.assertEqual(SourceEntityMapping.objects.count(), 2)
        self.assertEqual(a.entity.label, 'TP53')

    def test_source_scoped_names_never_merge(self):
        params = {'entity_type': 'compound', 'namespace': 'compound_name', 'identifier': 'Quercetin', 'taxon_key': 'unknown'}
        a, b = self.resolve(**params), self.resolve(self.rb, **params)
        self.assertNotEqual(a.entity_id, b.entity_id)

    def test_organisms_isolated_and_unknown_not_assumed_human(self):
        a, b = self.resolve(), self.resolve(self.rb, taxon_key='10090')
        c, d = self.resolve(taxon_key='unknown'), self.resolve(self.rb, taxon_key='unknown')
        self.assertEqual(len({row.entity_id for row in (a,b,c,d)}), 4)

    def test_gene_and_protein_are_distinct(self):
        protein = self.resolve()
        gene = self.resolve(entity_type='gene', namespace='entrez', identifier='7157')
        self.assertNotEqual(gene.entity_id, protein.entity_id)
        with self.assertRaises(ValidationError): self.resolve(entity_type='gene')

    def test_compound_global_key_is_not_species_dependent(self):
        a = self.resolve(entity_type='compound', namespace='PUBCHEM_CID', identifier='5280343')
        b = self.resolve(self.rb, entity_type='compound', namespace='pubchem', identifier='5280343', taxon_key='unknown')
        self.assertEqual(a.entity_id, b.entity_id)
        self.assertEqual(a.entity.taxon_key, 'not_applicable')

    def test_conflict_preserves_authoritative_binding_and_both_entities(self):
        mapping = self.resolve()
        other = KnowledgeEntity.objects.create(entity_type='protein', stable_id='other', label='Other', taxon_key='9606')
        conflict = self.resolve(self.rb, expected_entity=other)
        self.assertEqual(conflict.status, 'conflict')
        self.assertEqual(CanonicalIdentifier.objects.get().entity_id, mapping.entity_id)
        self.assertEqual(KnowledgeEntity.objects.count(), 2)
        self.assertEqual(conflict.metadata['proposedCanonicalId'], str(other.canonical_id))

    def test_repeated_observation_is_idempotent(self):
        a, b = self.resolve(), self.resolve()
        self.assertEqual(a.pk,b.pk)
        self.assertEqual(KnowledgeEntity.objects.count(), 1)

    def test_identifier_invalid_type_or_format_fails_closed(self):
        for params in [{'identifier':'not-uniprot'}, {'namespace':'../path'}, {'taxon_key':'human'}, {'entity_type':'unsupported'}]:
            with self.subTest(params=params), self.assertRaises(ValidationError): self.resolve(**params)
        self.assertEqual(KnowledgeEntity.objects.count(), 0)

    def test_raw_row_preserved_and_not_overwritten_in_same_version(self):
        raw = {'score': 'known target in HIT', 'score_type': 'source_original', 'target': None}
        first = preserve_source_record(release=self.ra, record_id='row-1', payload=raw, status='quarantined')
        self.assertEqual(first.pk, preserve_source_record(release=self.ra, record_id='row-1', payload=raw).pk)
        with self.assertRaises(ValidationError): preserve_source_record(release=self.ra, record_id='row-1', payload={'score':1})
        first.refresh_from_db()
        self.assertEqual(first.payload,raw)
        self.assertEqual(first.status,'quarantined')

    def test_source_record_and_mapping_release_cannot_mix(self):
        raw = preserve_source_record(release=self.ra, record_id='1', payload={'target':'P04637'})
        with self.assertRaises(ValidationError): self.resolve(self.rb, record=raw)

    def test_database_unique_constraint_guards_strong_identity(self):
        row = self.resolve()
        existing = CanonicalIdentifier.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CanonicalIdentifier.objects.create(entity=row.entity, entity_type='protein', namespace='uniprot', identifier=existing.identifier, taxon_key='9606', match_method='strong_identifier')

    def test_existing_pk_stable_id_and_canonical_uuid_not_changed(self):
        entity = KnowledgeEntity.objects.create(entity_type='gene', stable_id='legacy-G1', label='G1', source_release=self.ra)
        old = (entity.pk, entity.stable_id, entity.canonical_id)
        bootstrap_existing_master_ids(); bootstrap_existing_master_ids()
        entity.refresh_from_db()
        self.assertEqual((entity.pk,entity.stable_id,entity.canonical_id),old)
        self.assertEqual(CanonicalIdentifier.objects.count(),1)
        self.assertEqual(SourceEntityMapping.objects.count(),1)

    def test_summary_requires_admin_and_never_enables_scheduling(self):
        client = APIClient(); url = reverse('master-table-summary')
        self.assertEqual(client.get(url).status_code,401)
        ordinary = get_user_model().objects.create_user(username='master-reader')
        client.force_authenticate(ordinary)
        self.assertEqual(client.get(url).status_code,403)
        admin = get_user_model().objects.create_superuser(username='master-admin',email='master@example.test')
        client.force_authenticate(admin)
        response = client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.data['compatibility']['legacyIntegerPkPreserved'])
        self.a.refresh_from_db()
        self.assertIsNone(self.a.refresh_interval_hours)

    def test_legacy_alias_ambiguity_preserved_instead_of_first_match(self):
        entities = [KnowledgeEntity.objects.create(entity_type='gene', stable_id=f'old{i}', label=f'old{i}', source_release=self.ra) for i in range(2)]
        for entity in entities:
            EntityIdentifier.objects.create(entity=entity, source_release=self.ra, namespace='old-alias', identifier='SHARED')
        bootstrap_existing_master_ids()
        mapping = SourceEntityMapping.objects.get(namespace='old-alias')
        self.assertEqual(mapping.status,'ambiguous')
        self.assertIsNone(mapping.entity_id)
        self.assertEqual(set(mapping.metadata['candidateEntityPks']),{entity.pk for entity in entities})
