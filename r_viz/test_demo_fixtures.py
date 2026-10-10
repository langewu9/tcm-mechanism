import hashlib
import json
import unittest
from demo_fixtures import fixtures, DISCLAIMER


class DemoFixtureTests(unittest.TestCase):
    def test_all_current_chart_keys(self):
        charts = fixtures()
        self.assertEqual(len(charts), 14)
        self.assertEqual(len({chart['key'] for chart in charts}), 14)
        self.assertEqual(fixtures(), charts)
        for chart in charts:
            self.assertTrue(chart['synthetic'])
            payload = dict(chart['payload'])
            digest = payload.pop('inputSha256')
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            self.assertEqual(digest, hashlib.sha256(canonical.encode()).hexdigest())
            self.assertIn('非实验', payload['title'])
            self.assertEqual(payload['subtitle'], DISCLAIMER)
            self.assertTrue(payload['data'])

    def test_graph_endpoints_and_degrees(self):
        for chart in fixtures():
            payload = chart['payload']
            if payload['chartType'] != 'network':
                continue
            nodes = {node['id']: node for node in payload['data']}
            adjacent = {key: set() for key in nodes}
            for edge in payload['edges']:
                left, right = edge['source'], edge['target']
                self.assertNotEqual(left, right)
                adjacent[left].add(right)
                adjacent[right].add(left)
            for key, node in nodes.items():
                self.assertEqual(node['degree'], len(adjacent[key]))

    def test_volcano_selection_matches_thresholds(self):
        payload = next(chart['payload'] for chart in fixtures() if chart['key'] == 'proteomics_volcano')
        self.assertEqual(len(payload['data']), 180)
        for row in payload['data']:
            self.assertEqual(row['selected'], abs(row['log2FoldChange']) >= 1 and row['pValue'] <= 0.05)


if __name__ == '__main__':
    unittest.main()
