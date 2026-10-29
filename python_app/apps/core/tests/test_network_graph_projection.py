from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
from apps.core.services.network_pharmacology import build_network_pharmacology
from apps.core.services.visualization import build_chart_payload


class NetworkGraphProjectionTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='network-display-owner')
        source = DataSource.objects.create(slug='network-display-fixture', name='Synthetic display bounds')
        self.release = SourceRelease.objects.create(source=source, version='fixture-v1')
        self.herb = self.entity('herb', '合成药')
        self.disease = self.entity('disease', '合成病')

    def entity(self, kind, label):
        return KnowledgeEntity.objects.create(entity_type=kind, stable_id=f'fixture:{kind}:{label}',
            label=label, source_release=self.release)

    def result(self):
        return build_network_pharmacology(user=self.owner, herb_query=self.herb.label,
            disease_query=self.disease.label, complete=True, row_limit=50000, persist=False)

    def seed(self, size, *, parallel=False):
        targets = [KnowledgeEntity(entity_type='protein', label=f'FIXTURE_{i}', stable_id=f'fixture:target:{i}',
            source_release=self.release) for i in range(1 if parallel else size)]
        KnowledgeEntity.objects.bulk_create(targets)
        EvidenceRelation.objects.bulk_create([EvidenceRelation(subject=self.disease, object=targets[0] if parallel else targets[i],
            relation_type='disease_target', source_release=self.release, source_record_id=f'row:{i}') for i in range(size)])

    def test_node_cap_filters_edges_without_changing_full_statistics(self):
        self.seed(2105)
        result = self.result()
        ids = {node['id'] for node in result['network']['nodes']}
        self.assertTrue(all(edge['source'] in ids and edge['target'] in ids for edge in result['network']['links']))
        self.assertEqual(result['summary']['diseaseTargetCount'], 2105)
        self.assertEqual(len(result['raw']['diseaseTargets']), 2105)
        self.assertEqual(result['network']['totalNodeCount'], 2107)
        self.assertEqual(result['network']['totalLinkCount'], 2105)
        self.assertEqual(len(ids), 2000)
        self.assertTrue(result['limits']['nodesTruncated'])
        # The link count is below 4000, but node clipping still removed edges.
        self.assertTrue(result['limits']['linksTruncated'])
        self.assertEqual(EvidenceRelation.objects.count(), 2105)

    def test_parallel_source_rows_keep_their_full_count_outside_display_cap(self):
        self.seed(4005, parallel=True)
        result = self.result()
        self.assertEqual(result['summary']['diseaseTargetCount'], 1)
        self.assertEqual(len(result['raw']['diseaseTargets']), 4005)
        self.assertEqual(result['network']['totalLinkCount'], 4005)
        self.assertEqual(len(result['network']['links']), 4000)
        self.assertFalse(result['limits']['nodesTruncated'])
        self.assertTrue(result['limits']['linksTruncated'])

    def test_r_projection_discloses_parent_clipping_and_old_tasks_still_work(self):
        self.seed(3)
        result = self.result()
        task = AnalysisTask.objects.create(owner=self.owner, created_by=self.owner, task_type='network',
            status='succeeded', result=result)
        task.source_releases.add(self.release)
        self.assertFalse(result['limits']['nodesTruncated'])
        self.assertFalse(result['limits']['linksTruncated'])
        old = build_chart_payload(task, 'evidence_network')
        self.assertNotIn('原任务网络已裁剪', old['subtitle'])
        task.result = {**result, 'limits': {**result['limits'], 'nodesTruncated': True}}
        projected = build_chart_payload(task, 'evidence_network')
        self.assertIn('原任务网络已裁剪', projected['subtitle'])
        self.assertIn('完整证据见任务导出', projected['subtitle'])
        self.assertEqual(projected['data'], old['data'])
        self.assertEqual(projected['edges'], old['edges'])
        task.result = {**result, 'limits': {'targetsTruncated': False, 'linksTruncated': False}}
        self.assertEqual(build_chart_payload(task, 'evidence_network'), old)
