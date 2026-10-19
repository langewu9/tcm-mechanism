from django.test import SimpleTestCase

from apps.core.models import DataSource
from apps.sources.sqlite_sync import _row_entities_and_relations


class LegacyTargetIdentifierTests(SimpleTestCase):
    def target(self, label):
        source = DataSource(slug="synthetic-legacy", name="Synthetic legacy")
        entities, _ = _row_entities_and_relations(source, ("herb", 2, "测试中药", "测试成分", label))
        return next(entity for entity in entities if entity["entity_type"] == "protein")

    def test_protein_full_name_is_preserved_without_inventing_a_gene_symbol(self):
        for label in ["26S proteasome non-ATPase regulatory subunit 3", "Acetylcholinesterase"]:
            target = self.target(label)
            self.assertEqual(target["label"], label)
            self.assertEqual(target["metadata"]["identifierStatus"], "name_only")
            self.assertNotIn("symbol", target["metadata"])

    def test_symbol_shaped_source_value_is_explicitly_unverified(self):
        target = self.target("TP53")
        self.assertEqual(target["metadata"]["symbol"], "TP53")
        self.assertEqual(target["metadata"]["identifierStatus"], "unverified_symbol")

    def test_single_target_mode_preserves_punctuation_inside_a_protein_name(self):
        source = DataSource(slug="synthetic-legacy", configuration={"targetCellMode": "single"})
        label = "2-hydroxy-6-oxo-7-methylocta-2,4-dienoate hydrolase"
        entities, relations = _row_entities_and_relations(source, ("herb", 5, "测试中药", "测试成分", label))
        targets = [entity for entity in entities if entity["entity_type"] == "protein"]
        self.assertEqual([target["label"] for target in targets], [label])
        self.assertEqual(len(relations), 2)

    def test_legacy_list_mode_still_splits_multiple_identifiers(self):
        source = DataSource(slug="synthetic-legacy")
        entities, _ = _row_entities_and_relations(source, ("herb", 5, "测试中药", "测试成分", "TP53;EGFR"))
        self.assertEqual({entity["label"] for entity in entities if entity["entity_type"] == "protein"}, {"TP53", "EGFR"})
