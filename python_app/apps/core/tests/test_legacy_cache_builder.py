"""Regression: worksheet headers must never become scientific entities."""
from pathlib import Path
import ast
import sqlite3
import sys
import tempfile
from unittest import TestCase
from unittest.mock import patch

import openpyxl


class LegacyCacheHeaderTests(TestCase):
    def test_main_cache_builder_excludes_all_three_table_headers(self):
        root = str(Path(__file__).resolve().parents[4])
        sys.path.insert(0, root)
        self.addCleanup(lambda: sys.path.remove(root))
        from backend import cache_builder
        from backend.source_catalog import SOURCE_FILES
        main = ast.parse((Path(root) / "backend/data_service.py").read_text())
        source_map = next(node.value for node in main.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "SOURCE_FILES" for target in node.targets))
        self.assertEqual(SOURCE_FILES, ast.literal_eval(source_map))

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for metadata in SOURCE_FILES.values():
                workbook = openpyxl.Workbook()
                workbook.active.append([metadata["herb"], metadata["component"], metadata["target"]])
                workbook.active.append(["测试中药", "测试成分", "TP53"])
                workbook.save(directory / metadata["file"])
                workbook.close()
            for filename, headers, values in [
                ("疾病_中药.xlsx", ["疾病", "中药", "靶点基因"], ["测试疾病", "测试中药", "TP53"]),
                ("combined_results.xlsx", ["靶点基因", "疾病", "来源文件"], ["TP53", "测试疾病", "synthetic.xlsx"]),
            ]:
                workbook = openpyxl.Workbook()
                workbook.active.append(headers)
                workbook.active.append(values)
                workbook.save(directory / filename)
                workbook.close()
            with patch.multiple(cache_builder, DATABASE_DIR=directory, CACHE_DB=directory / "cache.sqlite3"):
                output = cache_builder.build_cache()
            with sqlite3.connect(output) as database:
                self.assertEqual(database.execute("SELECT COUNT(*) FROM herb_component_target").fetchone()[0], 5)
                self.assertEqual(database.execute("SELECT DISTINCT target FROM herb_component_target").fetchall(), [("TP53",)])
                self.assertEqual(database.execute("SELECT disease, herb, target FROM disease_herb_target").fetchall(), [("测试疾病", "测试中药", "TP53")])
                self.assertEqual(database.execute("SELECT disease, target FROM disease_target").fetchall(), [("测试疾病", "TP53")])
