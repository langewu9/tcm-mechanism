from io import BytesIO

from django.test import SimpleTestCase
from openpyxl import Workbook

from apps.proteomics.exceptions import ProteomicsInputError
from apps.proteomics.serializers import ProteomicsRunRequestSerializer
from apps.proteomics.services import _parse_delimited, _parse_xlsx, resolve_mapping


class ProteomicsColumnIntegrityTests(SimpleTestCase):
    def test_generated_duplicate_header_never_overwrites_an_existing_column(self):
        table = _parse_delimited(b'Gene,Gene,Gene_2\nFIRST,SECOND,THIRD\n', '.csv')
        self.assertEqual(len(set(table.columns)), 3)
        self.assertEqual([table.rows[0][column] for column in table.columns], ['FIRST', 'SECOND', 'THIRD'])
        self.assertEqual(table.rows[0]['Gene_2'], 'THIRD')

    def test_xlsx_and_tsv_preserve_all_values_with_suffix_collisions(self):
        workbook = Workbook();sheet = workbook.active
        sheet.append(['Gene', 'Gene', 'Gene_2']);sheet.append(['FIRST', 'SECOND', 'THIRD'])
        stream = BytesIO();workbook.save(stream);workbook.close()
        for table in [_parse_xlsx(stream.getvalue()), _parse_delimited(b'Gene\tGene\tGene_2\nFIRST\tSECOND\tTHIRD\n', '.tsv')]:
            self.assertEqual(len(set(table.columns)), 3)
            self.assertEqual([table.rows[0][column] for column in table.columns], ['FIRST', 'SECOND', 'THIRD'])

    def test_explicit_exact_mapping_uses_the_column_the_researcher_selected(self):
        columns = ['Gene Symbol', 'Gene-Symbol', 'log2FC']
        mapping = resolve_mapping(columns, {'gene_column': 'Gene-Symbol'})
        self.assertEqual(mapping.gene_column, 'Gene-Symbol')

    def test_api_mapping_names_reach_the_service_without_being_ignored(self):
        requested = {'geneColumn':'ChosenID','proteinColumn':'ChosenProtein','log2FcColumn':'ChosenEffect',
            'pValueColumn':'ChosenP','fdrColumn':'ChosenFDR','directionColumn':'ChosenDirection'}
        serializer = ProteomicsRunRequestSerializer(data={'mapping':requested})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        mapping = resolve_mapping(list(requested.values()), serializer.validated_data['mapping'])
        self.assertEqual(mapping.as_dict(), requested)

    def test_ambiguous_normalized_mapping_requires_an_exact_column_choice(self):
        columns = ['Gene Symbol', 'Gene-Symbol', 'log2FC']
        for mapping in [{}, {'gene_column': 'GENESYMBOL'}]:
            with self.assertRaises(ProteomicsInputError):
                resolve_mapping(columns, mapping)
        self.assertEqual(resolve_mapping(['Gene Symbol', 'log2FC'], {'gene_column': 'GENESYMBOL'}).gene_column, 'Gene Symbol')
