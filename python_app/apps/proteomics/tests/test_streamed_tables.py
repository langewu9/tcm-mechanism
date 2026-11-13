"""Exercise source-byte/encoding and resource boundaries of stored CSV parsing."""
import io
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.proteomics.exceptions import ProteomicsInputError
from apps.proteomics.services import _parse_delimited, parse_dataset_table


class GuardedSource(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.read_sizes = []

    def read(self, size=-1):
        if not 0 < size <= 64 * 1024:
            raise AssertionError("Stored CSV must use bounded raw reads")
        self.read_sizes.append(size)
        return super().read(size)


class StreamedTableTests(SimpleTestCase):
    def parse(self, content, extension=".csv"):
        source = GuardedSource(content)
        with patch("apps.proteomics.services.default_storage.open", return_value=source):
            table = parse_dataset_table("synthetic-source", "synthetic" + extension)
        self.assertTrue(source.read_sizes)
        return table

    def test_utf8_bom_duplicates_quotes_and_multiline_cells_match_original_parser(self):
        content = '\ufeffGene,Gene,Gene_2,Note\r\nA,B,C,"quoted, value\r\nsecond line"\r\n'.encode()
        self.assertEqual(self.parse(content), _parse_delimited(content, ".csv"))

    def test_late_gb18030_bytes_choose_encoding_for_the_whole_file(self):
        content = ("Gene,Label\n" + "A,plain\n" * 2000 + "B,中药\n").encode("gb18030")
        table = self.parse(content)
        self.assertEqual(table, _parse_delimited(content, ".csv"))
        self.assertEqual(table.rows[-1]["Label"], "中药")

    def test_utf8_character_crossing_raw_chunk_boundary_is_not_misdecoded(self):
        content = b"Gene,Label\n" + b"A,plain\n" * 8190 + "B,xx中\n".encode()
        self.assertEqual(content.index("中".encode()), 65535)
        self.assertEqual(self.parse(content).rows[-1]["Label"], "xx中")

    def test_tsv_keeps_commas_inside_the_source_cell(self):
        content = 'Gene\tLabel\nA\t成分甲,成分乙\n'.encode()
        self.assertEqual(self.parse(content, ".tsv").rows[0]["Label"], "成分甲,成分乙")

    def test_late_nul_and_incomplete_encoding_are_rejected(self):
        for content in (b"Gene,Label\n" + b"A,plain\n" * 2000 + b"B,\x00\n",
                        b"Gene,Label\nA,\x81"):
            with self.subTest(suffix=content[-10:]), self.assertRaises(ProteomicsInputError):
                self.parse(content)

    @override_settings(DATASET_UPLOAD_MAX_BYTES=64)
    def test_actual_byte_limit_applies_even_without_a_trusted_size_attribute(self):
        with self.assertRaisesMessage(ProteomicsInputError, "大小限制"):
            self.parse(b"Gene,Label\n" + b"A,plain\n" * 20)

    def test_empty_and_header_only_files_do_not_become_successful_datasets(self):
        for content in (b"", b"Gene,Label\n", b"\n\n"):
            with self.subTest(content=content), self.assertRaisesMessage(ProteomicsInputError, "没有可分析"):
                self.parse(content)

    @override_settings(PROTEOMICS_MAX_ROWS=2, PROTEOMICS_MAX_CELLS=4)
    def test_existing_cell_and_row_limits_still_reject_oversized_tables(self):
        with self.assertRaises(ProteomicsInputError):
            self.parse(b"Gene,Label\nA,one\nB,two\nC,three\n")
