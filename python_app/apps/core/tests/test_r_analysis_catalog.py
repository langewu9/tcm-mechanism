import hashlib
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask
from apps.core.services.visualization import build_chart_payload, VisualizationInputError


class RAnalysisCatalogTests(APITestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='r-catalog-owner', password='test-password')
        self.other = get_user_model().objects.create_user(username='r-catalog-other', password='test-password')
        self.ppi = {
            'source': 'STRING', 'sourceVersion': 'synthetic-test-v1', 'networkType': 'physical',
            'status': 'succeeded', 'requiredScore': 700, 'organism': 'Homo sapiens',
            'nodes': [{'id': 'a', 'label': 'SYNTHETIC_A', 'type': 'protein'}, {'id': 'b', 'label': 'SYNTHETIC_B', 'type': 'protein'}, {'id': 'isolated', 'label': 'SYNTHETIC_ISOLATE', 'type': 'protein'}],
            'edges': [{'source': 'a', 'target': 'b', 'score': 0.8}, {'source': 'b', 'target': 'a', 'score': 0.9}],
        }
        self.parent = AnalysisTask.objects.create(owner=self.owner, created_by=self.owner, task_type='proteomics', status='succeeded', result={'externalString': self.ppi, 'privateCaseText': 'never-send-this'})

    def payload(self, key):
        return build_chart_payload(self.parent, key)

    def test_ppi_deduplicates_and_ranks_actual_neighbors(self):
        payload = self.payload('ppi_network')
        self.assertEqual(len(payload['data']), 2)
        self.assertEqual(payload['edges'], [{'source': 'a', 'target': 'b', 'score': 0.9}])
        self.assertEqual([node['degree'] for node in payload['data']], [1, 1])
        self.assertIn('2/3', payload['subtitle'])
        self.assertNotIn('never-send-this', json.dumps(payload))
        self.assertEqual(self.payload('ppi_degree')['data'][0]['value'], 1)
        canonical = json.dumps({key: value for key, value in payload.items() if key != 'inputSha256'}, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        self.assertEqual(payload['inputSha256'], hashlib.sha256(canonical.encode()).hexdigest())

    def test_ppi_rejects_nonphysical_failed_missing_and_wrong_sources(self):
        for field, value in [('networkType', 'functional'), ('status', 'unavailable'), ('source', 'invented'), ('status', None), ('requiredScore', True)]:
            with self.subTest(field=field, value=value):
                self.parent.result = {'externalString': {**self.ppi, field: value}}
                with self.assertRaises(VisualizationInputError):
                    self.payload('ppi_network')

    def test_invalid_edges_and_below_threshold_cannot_create_graph(self):
        for edge in [{'source': 'a', 'target': 'a', 'score': 1}, {'source': 'a', 'target': 'missing', 'score': 1}, {'source': 'a', 'target': 'b', 'score': float('nan')}, {'source': 'a', 'target': 'b', 'score': True}, {'source': 'a', 'target': 'b', 'score': 0.699}]:
            self.parent.result = {'externalString': {**self.ppi, 'edges': [edge]}}
            with self.assertRaises(VisualizationInputError):
                self.payload('ppi_network')

    def test_bounded_subgraph_endpoint_integrity_and_determinism(self):
        nodes = [{'id': f'n{i:03}', 'label': f'SYNTHETIC_{i}', 'type': 'protein'} for i in range(100)]
        edges = [{'source': a['id'], 'target': b['id'], 'score': 0.8} for index, a in enumerate(nodes) for b in nodes[index + 1:]]
        self.parent.result = {'externalString': {**self.ppi, 'nodes': nodes, 'edges': edges}}
        first = self.payload('ppi_network')
        self.assertLessEqual(len(first['data']), 80)
        self.assertLessEqual(len(first['edges']), 500)
        ids = {node['id'] for node in first['data']}
        self.assertTrue(all(edge['source'] in ids and edge['target'] in ids for edge in first['edges']))
        self.assertEqual(first, self.payload('ppi_network'))
        self.assertIn('/4950', first['subtitle'])

    def test_gene_distribution_counts_unique_actual_genes(self):
        self.parent.result = {'network': {'nodes': [{'id': 't', 'label': 'SYNTHETIC_GENE', 'type': 'target'}, {'id': 'p', 'label': 'SYNTHETIC_PATHWAY', 'type': 'pathway'}, {'id': 'c', 'label': 'SYNTHETIC_COMPOUND', 'type': 'compound'}], 'links': [{'source': 't', 'target': 'p'}, {'source': 'p', 'target': 't'}, {'source': 'c', 'target': 'p'}]}}
        self.assertEqual(self.payload('gene_pathway_distribution')['data'], [{'label': 'SYNTHETIC_PATHWAY', 'value': 1}])
        self.assertEqual(len(self.payload('gene_pathway_network')['data']), 2)

    def test_zero_edges_never_become_demonstration_graph(self):
        self.parent.result = {'network': {'nodes': self.ppi['nodes'], 'links': []}}
        for key in ('evidence_network', 'gene_pathway_network', 'gene_pathway_distribution'):
            with self.assertRaises(VisualizationInputError):
                self.payload(key)

    def test_go_bar_preserves_source_and_fdr(self):
        self.parent.result = {'externalGProfiler': {'status': 'succeeded', 'sourceVersion': 'synthetic-v1', 'terms': [{'name': 'SYNTHETIC_TERM', 'source': 'GO:BP', 'adjustedPValue': 0.01}, {'name': 'invalid', 'source': 'KEGG', 'adjustedPValue': True}, {'name': 'not-significant', 'source': 'KEGG', 'adjustedPValue': 0.2}]}}
        payload = self.payload('proteomics_go_kegg_bar')
        self.assertEqual(len(payload['data']), 1)
        self.assertEqual(payload['data'][0]['value'], 2)
        self.assertIn('g:Profiler synthetic-v1', payload['subtitle'])

    def test_reactome_ratio_uses_actual_entity_counts(self):
        self.parent.result = {'externalReactome': {'status': 'succeeded', 'sourceVersion': 'synthetic-v1', 'pathways': [{'name': 'SYNTHETIC_PATHWAY', 'matchedEntities': 2, 'totalEntities': 10, 'fdr': 0.01}, {'name': 'invalid', 'matchedEntities': 2.5, 'totalEntities': 10, 'fdr': 0.01}]}}
        payload = self.payload('reactome_enrichment')
        self.assertEqual(payload['data'][0]['geneRatio'], 0.2)
        self.assertEqual(len(payload['data']), 1)

    def test_standalone_string_task_supported_and_wrong_task_rejected(self):
        self.parent.task_type = 'network'
        self.parent.result = {**self.ppi, 'analysisKind': 'string_ppi'}
        self.parent.result.pop('status')
        self.assertEqual(self.payload('ppi_network')['chartType'], 'network')
        self.parent.result['analysisKind'] = 'other'
        with self.assertRaises(VisualizationInputError):
            self.payload('ppi_network')

    @patch('apps.core.tasks.run_visualization_task.apply_async')
    @patch('apps.core.views.research.settings.R_VIZ_BASE_URL', 'http://r-viz:8001')
    @patch('apps.core.views.research.settings.R_VIZ_API_TOKEN', 'synthetic-test-token')
    def test_new_chart_api_enqueues_and_keeps_owner_boundary(self, enqueue):
        url = reverse('analysis-task-visualizations', args=[self.parent.pk])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(url, {'chartKey': 'ppi_network'}).status_code, 404)
        self.client.force_authenticate(self.owner)
        response = self.client.post(url, {'chartKey': 'ppi_network'})
        self.assertEqual(response.status_code, 202, response.data)
        job = AnalysisTask.objects.get(pk=response.data['id'])
        self.assertEqual(job.parent_task, self.parent)
        enqueue.assert_called_once_with(args=[job.pk])
        self.assertEqual(self.client.post(url, {'chartKey': 'ppi_network'}).status_code, 200)

    def test_unfinished_parent_is_rejected(self):
        self.parent.status = 'running'
        with self.assertRaises(VisualizationInputError):
            self.payload('ppi_network')

    def test_child_task_filter_is_scoped_to_current_owner(self):
        child = AnalysisTask.objects.create(owner=self.owner, task_type='visualization', parent_task=self.parent)
        AnalysisTask.objects.create(owner=self.other, task_type='visualization', parent_task=self.parent)
        self.client.force_authenticate(self.owner)
        response = self.client.get(reverse('analysis-task-list'), {'parent_task': self.parent.pk, 'task_type': 'visualization'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data['results']], [child.pk])
