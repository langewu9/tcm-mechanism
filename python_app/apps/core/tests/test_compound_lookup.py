from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITransactionTestCase

from apps.core.models import AnalysisTask, DataSource, EntityIdentifier, EvidenceRelation, KnowledgeEntity, SourceRelease
from apps.core.services.component_names import ALIAS_DATA
from apps.core.tasks import run_complete_evidence_task


@override_settings(COMPOUND_SOURCE_ALIASES={'HIT': ['source-hit']})
class CompoundLookupTests(APITransactionTestCase):
    # The real worker starts its own REPEATABLE READ transaction. Do not wrap
    # the fixture and worker invocation inside TestCase's outer transaction.
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='compound-lookup-owner')
        self.client.force_authenticate(self.user)
        self.source = DataSource.objects.create(slug='source-hit', name='Synthetic HIT source')
        self.other_source = DataSource.objects.create(slug='source-other', name='Synthetic other source')
        self.release = SourceRelease.objects.create(source=self.source, version='v1')
        self.other_release = SourceRelease.objects.create(source=self.other_source, version='v1')
        self.compound = self.entity('compound', 'fixture:c0671', 'Peiminine,Simperialine', metadata={
            'sourceEntityId': 'C0671', 'sourceReferences': [{'namespace': 'pubchem', 'identifier': 'CID:167691'}]})
        self.other_compound = self.entity('compound', 'other:c0671', 'Different compound', release=self.other_release,
                                          metadata={'sourceEntityId': 'C0671'})
        self.herb = self.entity('herb', 'fixture:herb', '合成测试药')
        self.target = self.entity('protein', 'fixture:target', 'TARGET')
        self.edges = [EvidenceRelation.objects.create(subject=self.herb, object=self.compound, relation_type='contains',
            source_release=self.release, source_record_id='row:contains'),
            EvidenceRelation.objects.create(subject=self.compound, object=self.target, relation_type='targets',
            source_release=self.release, source_record_id='row:targets')]

    def entity(self, kind, stable, label, *, metadata=None, release=None):
        return KnowledgeEntity.objects.create(entity_type=kind, stable_id=stable, label=label,
            source_release=release or self.release, metadata=metadata or {})

    def search(self, query, expected=200):
        response = self.client.post(reverse('batch-herb-evidence'), {'queryType': 'compound', 'queries': [query]}, format='json')
        self.assertEqual(response.status_code, expected, response.data)
        return response.data

    def ids(self, query):
        return {item['id'] for item in self.search(query)['results'][0]['matches']}

    def test_source_identifier_is_scoped_and_not_guessed_from_a_bare_number(self):
        self.assertEqual(self.ids('HIT:C0671'), {self.compound.pk})
        self.assertEqual(self.ids('source-other:C0671'), {self.other_compound.pk})
        self.assertEqual(self.ids('C0671'), set())
        self.assertEqual(self.ids('HIT:c0671'), set(), 'Provider IDs stay case-sensitive')

    def test_platform_keys_are_compound_only_and_bounded(self):
        self.assertEqual(self.ids(f'entity:{self.compound.pk}'), {self.compound.pk})
        self.assertEqual(self.ids(self.compound.stable_id), {self.compound.pk})
        self.assertEqual(self.ids(f'entity:{self.herb.pk}'), set())
        for value in ['entity:-1', 'entity:' + '9' * 100, 'pubchem:167691,1', 'chembl:bad']:
            self.search(value, 400)

    def test_only_explicit_old_main_aliases_expand_query_and_ids_remain_separate(self):
        one = self.entity('compound', 'fixture:quercetin', 'Quercetin')
        two = self.entity('compound', 'other:quercetin', 'Quercetin', release=self.other_release)
        for query in ['槲皮素', '栎精', 'Quercetin', 'Quercetinum']:
            self.assertEqual(self.ids(query), {one.pk, two.pk})
        item = self.search('槲皮素')['results'][0]
        self.assertTrue(item['ambiguous'])
        self.assertFalse(item['resolution']['identityMerged'])
        self.assertFalse(item['resolution']['authorityIdentityVerified'])
        self.assertEqual(item['resolution']['aliasSourceCommit'], '078d374')

    def test_comma_group_does_not_register_individual_aliases(self):
        self.compound.synonyms = ['Peiminine', 'Simperialine']
        self.compound.save(update_fields=['synonyms'])
        # An unreviewed string or existing free-form synonym array is not proof.
        self.assertEqual(self.ids('Peiminine'), set())
        self.assertEqual(self.ids('Simperialine'), set())
        self.assertEqual(self.ids('Peiminine,Simperialine'), {self.compound.pk})
        self.assertEqual(self.ids('HIT:C0671'), {self.compound.pk})
        self.assertEqual(self.ids('Peiminine, Simperialine'), set())

    def test_no_concatenation_or_punctuation_normalization_of_unreviewed_names(self):
        one = self.entity('compound', 'fixture:a', 'Unreviewed-A')
        two = self.entity('compound', 'fixture:b', 'Unreviewed-B')
        self.assertEqual(self.ids('Unreviewed-A,Unreviewed-B'), set())
        self.assertEqual(self.ids('Unreviewed A'), set())
        self.assertEqual(self.ids('Unreviewed-A'), {one.pk})
        self.assertNotEqual(one.pk, two.pk)

    def test_fuzzy_family_profile_cannot_create_exact_compound_matches(self):
        family = next(row for row in ALIAS_DATA['records'] if row.get('fuzzy'))
        self.entity('compound', 'fixture:ginsenoside', 'Ginsenoside Rg1')
        self.assertEqual(self.ids(family['aliases'][0]), set())

    def test_reported_reference_lookup_keeps_multiple_candidates_and_malformed_values_out(self):
        another = self.entity('compound', 'fixture:another-id', self.compound.label, metadata={
            'sourceEntityId': 'C9999', 'sourceReferences': [{'namespace': 'pubchem', 'identifier': '167691'}]})
        self.entity('compound', 'fixture:bad-cid', 'Bad reference', metadata={
            'sourceReferences': [{'namespace': 'pubchem', 'identifier': 'CID:167691,99'}]})
        item = self.search('pubchem:167691')['results'][0]
        self.assertEqual({row['id'] for row in item['matches']}, {self.compound.pk, another.pk})
        self.assertTrue(item['ambiguous'])
        self.assertTrue(all(proof['basis'][0]['method'] == 'source_reported_reference' for proof in item['resolution']['matchEvidence']))
        self.assertEqual(self.ids('CID:167691'), {self.compound.pk, another.pk})
        self.assertEqual(EntityIdentifier.objects.count(), 0)

    def test_registered_identifier_visibility_and_source_disabled_records_are_respected(self):
        EntityIdentifier.objects.create(entity=self.other_compound, source_release=self.other_release, namespace='pubchem', identifier='123')
        self.assertEqual(self.ids('pubchem:123'), {self.other_compound.pk})
        self.other_source.enabled = False
        self.other_source.save(update_fields=['enabled'])
        self.assertEqual(self.ids('pubchem:123'), set())
        self.assertEqual(self.ids('source-other:C0671'), set())
        self.source.enabled = False
        self.source.save(update_fields=['enabled'])
        self.assertEqual(self.ids('HIT:C0671'), set())

    def test_lookup_never_rewrites_entities_relations_or_unverified_source_claims(self):
        before = list(KnowledgeEntity.objects.order_by('pk').values())
        for query in ['HIT:C0671', 'pubchem:167691', self.compound.label]:
            self.assertEqual(self.ids(query), {self.compound.pk})
        self.assertEqual(before, list(KnowledgeEntity.objects.order_by('pk').values()))
        self.assertEqual(EvidenceRelation.objects.count(), 2)
        self.assertFalse(AnalysisTask.objects.exists())

    def test_saved_query_freezes_lookup_basis_and_retains_existing_entity_ids(self):
        preview = self.search('HIT:C0671')
        response = self.client.post(reverse('catalog-evidence-analysis'), {'queryType': 'compound', 'queries': ['HIT:C0671'],
            'expectedResultSha256': preview['resultSha256']}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        task = AnalysisTask.objects.get(pk=response.data['id'])
        self.assertEqual(task.input_parameters['algorithmVersion'], 'catalog-evidence-0.5')
        self.assertEqual(task.result['queryResolutions'][0]['resolution'], preview['results'][0]['resolution'])
        self.assertEqual({row['id'] for row in task.result['evidenceRecords']}, {row.pk for row in self.edges})

    def test_complete_task_freezes_lookup_basis_in_paginated_export_table(self):
        preview = self.search('HIT:C0671')
        with patch('apps.core.tasks.run_complete_evidence_task.apply_async'):
            response = self.client.post(reverse('catalog-evidence-analysis'), {'queryType': 'compound', 'queries': ['HIT:C0671'],
                'expectedResultSha256': preview['resultSha256'], 'complete': True}, format='json')
        self.assertEqual(response.status_code, 202)
        task = AnalysisTask.objects.get(pk=response.data['id'])
        self.assertEqual(run_complete_evidence_task(task.pk)['status'], 'succeeded')
        frozen = task.snapshot_rows.get(table='queries').payload
        self.assertEqual(frozen['resolution'], preview['results'][0]['resolution'])
        self.assertEqual(frozen['matchedIds'], [self.compound.pk])

    def test_alias_configuration_change_invalidates_an_old_preview(self):
        self.entity('compound', 'fixture:quercetin', 'Quercetin')
        preview = self.search('槲皮素')
        changed = {**ALIAS_DATA, 'sourceCommit': 'different-reviewed-table'}
        with patch('apps.core.services.compound_lookup.ALIAS_DATA', changed):
            response = self.client.post(reverse('catalog-evidence-analysis'), {'queryType': 'compound', 'queries': ['槲皮素'],
                'expectedResultSha256': preview['resultSha256']}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertFalse(AnalysisTask.objects.exists())
