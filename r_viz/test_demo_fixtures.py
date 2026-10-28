import ast
import hashlib
import json
from pathlib import Path
import unittest
from demo_fixtures import fixtures, DISCLAIMER


class DemoFixtureTests(unittest.TestCase):
    def test_demo_keys_cover_backend_chart_choices(self):
        source = Path(__file__).resolve().parents[1] / 'python_app/apps/core/serializers/research.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        serializer = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'VisualizationRequestSerializer')
        field = next(node for node in serializer.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'chartKey' for target in node.targets))
        choices = next(keyword.value for keyword in field.value.keywords if keyword.arg == 'choices')
        self.assertEqual({chart['key'] for chart in fixtures()}, set(ast.literal_eval(choices)))

    def test_all_current_chart_keys(self):
        charts = fixtures()
        self.assertEqual(len(charts), 16)
        self.assertEqual(len({chart['key'] for chart in charts}), 16)
        self.assertEqual(fixtures(), charts)
        for chart in charts:
            self.assertTrue(chart['synthetic'])
            payload = dict(chart['payload'])
            digest = payload.pop('inputSha256')
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            self.assertEqual(digest, hashlib.sha256(canonical.encode()).hexdigest())
            self.assertIn('合成演示', payload['title'])
            self.assertEqual(payload['subtitle'], DISCLAIMER)
            self.assertTrue(payload['data'])

    def test_graph_endpoints_and_degrees(self):
        for chart in fixtures():
            payload = chart['payload']
            if payload['chartType'] != 'network':
                continue
            nodes = {node['id']: node for node in payload['data']}
            self.assertGreaterEqual(len(nodes), 60)
            self.assertLessEqual(len(nodes), 80)
            self.assertGreaterEqual(len(payload['edges']), 200)
            self.assertLessEqual(len(payload['edges']), 500)
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
        self.assertEqual(len(payload['data']), 1200)
        for row in payload['data']:
            self.assertEqual(row['selected'], abs(row['log2FoldChange']) >= 1 and row['pValue'] <= 0.05)


if __name__ == '__main__':
    unittest.main()
