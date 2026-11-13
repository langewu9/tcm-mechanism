"""Synthetic privacy/integrity checks; never opens the user's clinical files."""
from io import BytesIO
import json
from pathlib import Path
import stat
import tempfile
import unittest
from zipfile import ZipFile

from openpyxl import Workbook
if __package__:
    from .inventory_case_formula_sources import (
        COMMON_FIELDS, InventoryError, WORKBOOK_NAME, inventory_archive,
        inventory_workbook, write_private_report,
    )
else:
    from inventory_case_formula_sources import (
        COMMON_FIELDS, InventoryError, WORKBOOK_NAME, inventory_archive,
        inventory_workbook, write_private_report,
    )


def workbook(*, matching=False, bad_header=False):
    book = Workbook(); book.remove(book.active)
    for name in [*'ABCDEFGH', 'Sheet1']:
        sheet = book.create_sheet(name)
        fields = [*COMMON_FIELDS, *(['证型', '患者编号'] if name == 'Sheet1' else ['方剂名称', '治法'])]
        if bad_header and name == 'A': fields.append('SYNTHETIC_PRIVATE_HEADER')
        sheet.append(fields)
        if name not in {'A', 'Sheet1'}: continue
        for index in range(2):
            row = {key: 'SYNTHETIC_' + key for key in fields}
            row.update({'姓名缩写': 'PATIENT_DO_NOT_EXPORT', '具体药物': 'PRIVATE_DRUG_TEXT',
                        '方剂名称': 'PRIVATE_FORMULA' + (' ' if index else ''),
                        '证型': 'PRIVATE_SYNDROME' + (' ' if index else '')})
            if name == 'Sheet1' and not matching: row['具体药物'] += '_UNMATCHED'
            sheet.append([row[key] for key in fields])
    stream = BytesIO(); book.save(stream); book.close()
    return stream.getvalue()


class CaseFormulaInventoryTests(unittest.TestCase):
    def test_aggregate_report_separates_original_labels_and_does_not_export_values(self):
        report = inventory_workbook(workbook(), 'synthetic.xlsx')
        self.assertEqual(report['detailGroup']['nonemptyDataRows'], 2)
        self.assertEqual(report['summaryGroup']['nonemptyDataRows'], 2)
        self.assertEqual(report['detailGroup']['formulaLabels']['rawDistinct'], 2)
        self.assertEqual(report['detailGroup']['formulaLabels']['trimmedWhitespaceDistinct'], 1)
        self.assertEqual(report['exactSharedFieldComparison']['summaryRowsWithAnyExactDetailMatch'], 0)
        rendered = json.dumps(report)
        for forbidden in ['PATIENT_DO_NOT_EXPORT', 'PRIVATE_DRUG_TEXT', 'PRIVATE_FORMULA', 'PRIVATE_SYNDROME']:
            self.assertNotIn(forbidden, rendered)

    def test_multiple_exact_matches_are_reported_without_inventing_a_unique_join(self):
        report = inventory_workbook(workbook(matching=True), 'synthetic.xlsx')
        self.assertEqual(report['exactSharedFieldComparison']['summaryRowsWithMultipleExactDetailMatches'], 2)
        self.assertEqual(report['exactSharedFieldComparison']['summaryRowsWithOneExactDetailMatch'], 0)
        self.assertFalse(report['exactSharedFieldComparison']['individualMatchesExported'])

    def test_unknown_headers_are_rejected_without_echoing_them(self):
        with self.assertRaises(InventoryError) as error:
            inventory_workbook(workbook(bad_header=True), 'synthetic.xlsx')
        self.assertNotIn('SYNTHETIC_PRIVATE_HEADER', str(error.exception))

    def test_archive_is_read_only_and_result_remains_pending_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'synthetic.zip'
            with ZipFile(archive, 'w') as container:
                container.writestr('fixtures/' + WORKBOOK_NAME, workbook())
            before = archive.read_bytes()
            report = inventory_archive(archive)
            self.assertEqual(archive.read_bytes(), before)
            self.assertEqual(report['reviewStatus'], 'need_review')
            self.assertFalse(report['boundaries']['imported'])
            self.assertFalse(report['boundaries']['networkAccess'])
            self.assertFalse(report['boundaries']['canonicalCompositionGenerated'])

    def test_private_output_permissions_no_overwrite_and_no_directory_permission_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / 'private'; path = parent / 'report.json'
            write_private_report(path, {'synthetic': True})
            self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError): write_private_report(path, {'replaced': True})
            self.assertEqual(json.loads(path.read_text()), {'synthetic': True})
            parent.chmod(0o755)
            with self.assertRaises(InventoryError): write_private_report(parent / 'other.json', {})
            self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o755)

    def test_missing_archive_is_a_safe_error(self):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(InventoryError):
            inventory_archive(Path(temporary) / 'missing.zip')


if __name__ == '__main__': unittest.main()
