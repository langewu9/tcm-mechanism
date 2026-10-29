"""Read-only local mapping/QC audit with explicitly synthetic measurements.

No real experiment was identified in the current working datasets. Statistical
references come from the existing local R t.test/p.adjust implementation; no
model, external lookup, catalogue mutation or persisted research task is used.
"""
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from postgres_acceptance import APP, ROOT, environment

JOB = ROOT / 'python_app/var/proteomics-business-2026-10-21'
THRESHOLDS = {'log2FcMin': 1, 'pValueMax': .05, 'fdrMax': .05}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False));path.chmod(0o600)


def encode_csv(headers, rows):
    output = io.StringIO(newline='');writer = csv.writer(output);writer.writerow(headers);writer.writerows(rows)
    return output.getvalue().encode('utf-8-sig')


def main():
    output = JOB / 'local-audit.json'
    if output.exists():
        raise ValueError('Refusing to replace earlier audit evidence.')
    environment();sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.db import connection, transaction
    from apps.core.models import AnalysisTask, ResearchDataset, KnowledgeEntity
    from apps.proteomics.services import _parse_delimited, _parse_rows, _build_result, resolve_mapping, ColumnMapping, ProteomicsInputError
    from apps.proteomics.raw_matrix import analyze_raw_matrix
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
        target = KnowledgeEntity.objects.filter(entity_type='protein', source_release__source_id=5,
            is_active=True, metadata__identifierStatus='unverified_symbol').order_by('pk').first()
        assert target and not target.organism and target.metadata.get('sourceEntityId')
        headers = ['Gene Symbol', 'Gene-Symbol', 'log2FC', 'PValue', 'FDR', 'Sample', 'Sample', 'Sample_2']
        measurements = [
            (target.stable_id, '2', '.01', '.01'), ('BCL2', '2', '.01', '.01'),
            ('Unknown, Protein Pair', '2', '.01', '.01'), ('SYNTHETICX', '2', '.01', '.01'),
            ('BAX', '1', '.05', '.05'), ('LOW_FC', '.99', '.01', '.01'),
            ('BAD_P', '2', '1.1', '.01'), ('BAD_FDR', '2', '.01', '-.1'),
            ('BAD_FC', 'invalid', '.01', '.01'), ('', '2', '.01', '.01'),
            ('MISSING_FDR', '2', '.01', ''), ('FDR_FIRST', '2', '.9', '.01'),
            ('SYNTHETICX', '-2', '1%', '2%'), ('NO_SIGNIFICANCE', '2', '', ''), ('MISSING_FC', '', '.01', '.01'),
        ]
        contents = encode_csv(headers, [[f'WRONG_COLUMN_{i}', *row, 'KEEP1', 'KEEP2', 'KEEP3'] for i, row in enumerate(measurements)])
        input_path = JOB / 'synthetic-differential-columns.csv';input_path.write_bytes(contents);input_path.chmod(0o600)
        table = _parse_delimited(contents, '.csv')
        assert table.columns[-3:] == ['Sample', 'Sample_3', 'Sample_2']
        assert all([row[key] for key in table.columns[-3:]] == ['KEEP1', 'KEEP2', 'KEEP3'] for row in table.rows)
        try:
            resolve_mapping(table.columns, {})
        except ProteomicsInputError:
            pass
        else:
            raise AssertionError('Ambiguous automatic column selection must stop.')
        mapping = resolve_mapping(table.columns, {'gene_column': 'Gene-Symbol'})
        rows, qc = _parse_rows(table.rows, mapping, THRESHOLDS)
        expected_selected = [0, 1, 2, 3, 4, 10, 11, 12]
        assert [row.row_index for row in rows if row.selected] == expected_selected
        assert qc['invalidNumericValueRowCount'] == 3 and qc['duplicateIdentifierCount'] == 1
        assert qc['missingIdentifierCount'] == 1 and qc['excludedRowCount'] == 7
        dataset = ResearchDataset(owner_id=2, original_filename=input_path.name,
            content_sha256=hashlib.sha256(contents).hexdigest(), name='SYNTHETIC audit only')
        task = AnalysisTask(owner_id=2, dataset=dataset, task_type='proteomics', input_parameters={'thresholds': THRESHOLDS})
        result, stored, releases = _build_result(rows, [], table.columns, mapping, qc, task)
        assert stored[0].matched_entity_id == target.pk and stored[0].mapping_status == 'unverified'
        assert stored[0].normalized_symbol == target.label
        assert any(item['namespace'] == 'source_entity' and item['identifier'] == target.metadata['sourceEntityId'] for item in stored[0].external_identifiers)
        for index, label in [(1, 'BCL2'), (4, 'BAX')]:
            assert KnowledgeEntity.objects.filter(entity_type__in=['gene', 'protein'], is_active=True,
                source_release__source__enabled=True, label__iexact=label).count() > 1
            assert stored[index].mapping_status == 'ambiguous' and not stored[index].normalized_symbol and not stored[index].matched_entity_id
        assert stored[2].original_label == 'Unknown, Protein Pair' and stored[2].mapping_status == 'unmapped'
        assert stored[3].mapping_status == 'unverified' and not stored[3].matched_entity_id
        assert result['summary']['databaseMappedCount'] == 0 and not result['network']['links']
        fields = ['row_index','original_label','normalized_symbol','mapping_status','mapping_source','external_identifiers',
            'matched_entity_id','log2_fold_change','p_value','fdr','selected','exclusion_reasons','qc_warnings']
        report = {'syntheticMeasurements': True, 'databaseReadOnly': True, 'externalCalls': False, 'identityMerged': False,
            'differential': {'file': input_path.name, 'sha256': dataset.content_sha256, 'mapping': mapping.as_dict(),
                'expectedSelectedIndices': expected_selected, 'qc': qc, 'summary': result['summary'],
                'rows': [{key: getattr(row, key) for key in fields} for row in stored]}, 'matrixCases': []}

    # Existing local R runtime supplies a separate implementation of t tests
    # and BH adjustment, rather than using the Python result as its own oracle.
    matrix_headers = ['Gene', 'C1', 'C2', 'C3', 'T1', 'T2', 'T3']
    matrix_values = [
        ['SYNTH_MATRIX_UP',10,10.2,9.8,12,12.5,11.6],
        ['SYNTH_MATRIX_DOWN',15,14.6,15.3,12,12.1,11.7],
        ['SYNTH_MATRIX_NULL',10,10.3,9.8,10.1,10.2,9.8],
        ['SYNTH_MATRIX_MISSING',10,'',9.8,12,12.5,11.6],
        ['SYNTH_MATRIX_INVALID',10,'invalid',9.8,12,12.5,11.6],
        ['SYNTH_MATRIX_FLAT',10,10,10,12,12,12],
        ['',10,10.2,9.8,12,12.5,11.6],
    ]
    matrix_bytes = encode_csv(matrix_headers, matrix_values)
    matrix_path = JOB / 'synthetic-raw-matrix.csv';matrix_path.write_bytes(matrix_bytes);matrix_path.chmod(0o600)
    script = JOB / 'r-statistics-reference.R'
    script.write_text('''d <- read.csv("synthetic-raw-matrix.csv", check.names=FALSE, na.strings=c("", "invalid"))
for (mode in c("unpaired", "paired")) {
  out <- data.frame(row_index=integer(), effect=numeric(), p_value=numeric())
  for (i in seq_len(nrow(d))) {
    if (is.na(d$Gene[i]) || !nzchar(d$Gene[i])) next
    c <- as.numeric(d[i,c("C1","C2","C3")]); t <- as.numeric(d[i,c("T1","T2","T3")])
    if (anyNA(c(c,t))) next
    test <- tryCatch(t.test(t,c,paired=(mode=="paired"),var.equal=FALSE), error=function(e) NULL)
    if (is.null(test)) next
    out <- rbind(out,data.frame(row_index=i-1L,effect=mean(t)-mean(c),p_value=test$p.value))
  }
  out$fdr <- p.adjust(out$p_value,method="BH")
  write.csv(out,paste0("r-reference-",mode,".csv"),row.names=FALSE)
}
''');script.chmod(0o600)
    r_home = ROOT / 'python_app/var/local-runtime/root/usr/lib/R'
    runtime = ROOT / 'python_app/var/local-runtime/root/usr/lib/x86_64-linux-gnu'
    r_env = {**os.environ, 'R_HOME': str(r_home), 'R_LIBS_SITE': str(r_home/'site-library'),
        'LD_LIBRARY_PATH': ':'.join(map(str, [r_home/'lib', runtime, runtime/'blas', runtime/'lapack']))}
    subprocess.run([str(r_home/'bin/exec/R'), '--vanilla', '--slave', '-f', str(script)], cwd=JOB, env=r_env, check=True, timeout=40)
    matrix_rows = _parse_delimited(matrix_bytes, '.csv').rows
    for mode in ['unpaired','paired']:
        design = {'identifierColumn':'Gene','sampleColumns':matrix_headers[1:], 'controlSamples':['C1','C2','C3'],
            'treatmentSamples':['T1','T2','T3'], 'designType':mode, 'valuesAreLog2':True,
            'normalization':'none','missingPolicy':'complete_rows'}
        if mode == 'paired':
            design['samplePairs'] = [{'pairId':f'p{i}', 'controlSample':f'C{i}', 'treatmentSample':f'T{i}'} for i in range(1,4)]
        derived, excluded, details, warnings = analyze_raw_matrix(matrix_rows, design)
        with (JOB/f'r-reference-{mode}.csv').open() as stream:
            reference = list(csv.DictReader(stream))
        assert {int(row['row_index']) for row in reference} == {0,1,2}
        for row in reference:
            actual = derived[int(row['row_index'])]
            for expected_key, actual_key in [('effect','__log2fc'), ('p_value','__pvalue'), ('fdr','__fdr')]:
                assert math.isclose(float(actual[actual_key]), float(row[expected_key]), rel_tol=1e-9, abs_tol=1e-12), (mode, row, actual)
        assert excluded == {3:['incomplete_samples'],4:['invalid_sample_values'],5:['test_not_estimable'],6:['missing_identifier']}
        parsed, _ = _parse_rows(derived, ColumnMapping('__identifier','','__log2fc','__pvalue','__fdr',''), THRESHOLDS)
        assert [row.row_index for row in parsed if row.selected] == [0,1]
        report['matrixCases'].append({'design':design, 'file':matrix_path.name, 'reference':reference,
            'expectedExcluded':excluded, 'expectedSelectedIndices':[0,1], 'rReferenceMatches':True, 'qc': details['qc']})
    report['passed'] = True
    write_json(output, report)
    print(json.dumps({'passed':True, 'syntheticOnly':True, 'differentialRows':15,
        'selectedRows':8, 'confirmedDatabaseMappings':0, 'matrixDesignsComparedWithLocalR':2},ensure_ascii=False))


if __name__ == '__main__':
    main()
