"""Offline retrospective reproduction, separate from original holdout evaluation.

No download or acquisition-gate replay. Generates nontruncated fixtures from
immutable raw members using release-verified preparation functions. Registered
truncated fixtures are hash-verified and copied byte for byte to preserve their
exact damaged inputs across library versions. Requires the original holdout
evaluation receipt before reading cached holdout data. Leaves references intact.
"""
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import csv,json,argparse,hashlib,sqlite3,importlib.util,datetime,shutil
from decimal import Decimal
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def readcsv(p,encoding='utf-8-sig'):
 with p.open(encoding=encoding,newline='') as f:return list(csv.DictReader(f))
def load_frozen(reference):
 path=reference/'holdout'/'generator_sources_frozen'/'prepare_data.py'
 receipt=json.loads((reference/'holdout'/'generator_release.json').read_text(encoding='utf-8'))
 expected=next(x['sha256'] for x in receipt['generator_files'] if x['path']=='prepare_data.py');assert sha(path)==expected
 spec=importlib.util.spec_from_file_location('frozen_preparation',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def parse(p,encoding='utf-8-sig'):
 if p.suffix=='.csv':return readcsv(p,encoding)
 if p.suffix=='.json':return json.loads(p.read_text(encoding=encoding))
 if p.suffix=='.sqlite':
  with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as c:c.row_factory=sqlite3.Row;return [dict(r) for r in c.execute('select * from canonical_records')]
 if p.suffix=='.xlsx':
  from openpyxl import load_workbook
  wb=load_workbook(p,read_only=True,data_only=True);a=list(wb.worksheets[0].values);wb.close();return [dict(zip(a[0],r)) for r in a[1:]]
 if p.suffix=='.docx':
  from docx import Document
  a=[[c.text for c in r.cells] for r in Document(p).tables[0].rows];return [dict(zip(a[0],r)) for r in a[1:]]
 if p.suffix=='.pdf':
  from pypdf import PdfReader
  lines=[x.strip() for page in PdfReader(p).pages for x in (page.extract_text() or '').splitlines() if x.strip()];a=[x.split('|') for x in lines];return [dict(zip(a[0],r)) for r in a[1:]]
 raise ValueError(p)
def selected_holdout(reference,output,prep):
 # A completed original-study receipt is mandatory. This is retrospective reuse,
 # not another untouched-holdout evaluation and not parser training.
 original=reference/'holdout'/'first_evaluation_receipt.json'
 if not original.exists():raise RuntimeError('Original holdout has not been evaluated yet; offline reproduction may not read it.')
 evaluation=json.loads(original.read_text(encoding='utf-8'))
 if not evaluation.get('finished_at_utc'):raise RuntimeError('Original holdout evaluation is incomplete.')
 acquired=json.loads((reference/'holdout'/'acquisition_receipt.json').read_text(encoding='utf-8'));info=prep.SOURCES['holdout'];raw=reference/'raw'/'holdout'/info['member'];assert sha(raw)==acquired['raw_member_sha256']
 rows=[];lineage=[]
 for rownum,r in enumerate(readcsv(raw),2):
  value=r['pm2.5']
  if not prep.finite(value):continue
  rid=f'B{len(rows)+1:04d}';normalized=prep.canonical_decimal(value);loc=f'https://archive.ics.uci.edu/dataset/381#{info["member"]}:row={rownum}:col=pm2.5';rows.append(dict(zip(prep.FIELDS,[rid,'BeijingPM25','public_real','pm2.5','ug/m3',normalized,loc])));lineage.append({'record_id':rid,'source_member':info['member'],'physical_row':rownum,'source_column':'pm2.5','original_value':value,'canonical_value':normalized,'source_sha256':sha(raw)})
  if len(rows)==120:break
 assert len(rows)==120
 (output/'raw'/'holdout').mkdir(parents=True);shutil.copyfile(raw,output/'raw'/'holdout'/raw.name)
 return rows,lineage
def transformed(truth,case,filename,fields):
 headers=list(fields);rows=[dict(r) for r in truth]
 changed=dict(truth[0],value=str(Decimal(truth[0]['value'])+Decimal(1)))
 if case=='columns_reordered':headers.reverse()
 elif case=='extra_column':headers+=['ignored_note'];rows=[dict(r,ignored_note='controlled-extra-column') for r in rows]
 elif case=='missing_required_value':headers.remove('value')
 elif case=='duplicate_id_same_value':rows.append(dict(rows[0]))
 elif case=='duplicate_id_conflict':rows.append(changed)
 elif case=='explicit_de-DE':rows=[dict(r,value=r['value'].replace('.',',')) for r in rows]
 elif case.startswith('cross_file') and filename.startswith('second'):
  rows=[dict(r) for r in truth[:10]]
  if case=='cross_file_conflict':rows[0]=changed
 return headers,rows
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--reference-data',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--partitions',default='base,late_json,holdout');a=ap.parse_args();reference=a.reference_data.resolve();out=a.output.resolve();parts=a.partitions.split(',')
 if out.exists():raise RuntimeError('Refuse existing reproduction output directory.')
 if out==reference or reference in out.parents:raise RuntimeError('Reproduction output must be outside the reference data directory.')
 if any(p not in ['base','late_json','holdout'] for p in parts):raise ValueError(parts)
 prep=load_frozen(reference);out.mkdir(parents=True);before={p:sha(reference/p) for p in ['raw/base/TS1.txt','raw/base/ai4i2020.csv']}
 base,lineage,sources=prep.select_base(reference/'raw'/'base',out/'raw'/'base');truths={'base':base,'late_json':base}
 if 'holdout' in parts:
  held,held_lineage=selected_holdout(reference,out,prep);truths['holdout']=held;prep.csvwrite(out/'holdout'/'source_lineage.csv',held_lineage)
 results=[]
 for partition in parts:
  truth=truths[partition];prep.csvwrite(out/partition/'canonical_ground_truth.csv',truth,prep.FIELDS);expected=readcsv(reference/partition/'canonical_ground_truth.csv');assert truth==expected,partition
  registered=readcsv(reference/partition/'data_manifest.csv');jobs=[]
  for row in registered:
   if row['case']=='truncated':continue
   p=out/row['relative_path'];headers,rr=transformed(truth,row['case'],p.name,prep.FIELDS);encoding=row.get('actual_encoding','utf-8');encoding='utf-8' if encoding=='format_defined' else encoding
   if p.suffix=='.json':
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps([{k:r.get(k,'') for k in headers} for r in rr],ensure_ascii=False,indent=2),encoding=encoding)
   else:prep.write_fixture(p,headers,rr,row['format'],jobs,encoding=encoding)
  for job in jobs:prep.ooxml_write(job)
  for row in registered:
   if row['case']!='truncated':continue
   original=reference/row['relative_path'];assert sha(original)==row['sha256'],row['relative_path']
   p=out/row['relative_path'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,p)
   assert sha(p)==row['sha256'],row['relative_path']
  for row in registered:
   p=out/row['relative_path'];original=reference/row['relative_path'];assert sha(original)==row['sha256'];equal=sha(p)==row['sha256'];semantic=None
   if not equal and row['case']!='truncated':
    encoding=row.get('actual_encoding','utf-8');encoding='utf-8-sig' if encoding=='format_defined' else encoding;semantic=parse(p,encoding)==parse(original,encoding)
   if not equal and semantic is not True:raise AssertionError('Prepared fixture does not reproduce registered bytes or parsed fields: '+row['relative_path'])
   method='verified_reference_copy_for_truncated_fixture' if row['case']=='truncated' else 'generated_from_public_raw_members'
   results.append({'path':row['relative_path'],'preparation_method':method,'reference_sha256':row['sha256'],'rebuilt_sha256':sha(p),'byte_identical':equal,'semantic_equal_if_needed':semantic,'expected_outcome':row['expected_outcome']})
  # Manifests are copied as original fixed experiment plans. Their original hashes
  # describe the reference corpus; rebuilt hashes are explicitly in this report.
  for manifest in (reference/partition).rglob('*manifest.json'):
   if manifest.name=='manifest.json' or manifest.parent.name=='truncated':
    target=out/manifest.relative_to(reference);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(manifest,target)
  for name in ['data_manifest.csv','expected_outcomes.json']:
   source=reference/partition/name
   if source.exists():shutil.copyfile(source,out/partition/name)
  shutil.copyfile(reference/partition/'data_manifest.csv',out/partition/'registered_reference_data_manifest.csv')
  receipts=out/'reference_receipts'/partition
  for name in ['extension_receipt.json','acquisition_receipt.json','first_evaluation_receipt.json','generator_release.json']:
   source=reference/partition/name
   if source.exists():receipts.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,receipts/name)
 assert all(sha(reference/p)==h for p,h in before.items())
 generated=sum(row['preparation_method']=='generated_from_public_raw_members' for row in results);copied=sum(row['preparation_method']=='verified_reference_copy_for_truncated_fixture' for row in results)
 assert generated+copied==len(results)
 report={'purpose':'retrospective_offline_reproduction_not_original_holdout_evaluation','started_original_study_gate_replayed':False,'network_access':False,'partitions':parts,'fixture_files':len(results),'generated_fixture_files':generated,'reference_copied_fixture_files':copied,'all_fixtures_prepared_and_verified':True,'generated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reference_raw_files_unchanged':True,'files':results}
 prep.jsonwrite(out/'offline_reproduction_report.json',report);prep.csvwrite(out/'rebuilt_file_hashes.csv',results)
 (out/'REPRODUCTION_HASHES.txt').write_text('This is retrospective offline reproduction, not a new first holdout evaluation.\n\nNontruncated fixtures are generated from the public raw members and checked against registered bytes or parsed fields. Pre-registered truncated fixtures are verified against the reference SHA-256 and copied byte for byte to preserve the exact damaged inputs across library versions. They are not claimed to have been regenerated.\n\nGenerated fixture files: '+str(generated)+'\nReference-copied truncated fixture files: '+str(copied)+'\n\nCopied data_manifest.csv and expected_outcomes.json are the fixed reference experiment plans. Their SHA-256 columns describe the reference corpus. Actual output SHA-256 values and each preparation_method are in rebuilt_file_hashes.csv; the full comparison and counts are in offline_reproduction_report.json. Any source receipts are reference copies under reference_receipts.\n',encoding='utf-8')
 print(json.dumps({'fixtures':len(results),'generated_fixture_files':generated,'reference_copied_fixture_files':copied,'all_fixtures_prepared_and_verified':True,'network_access':False,'original_holdout_receipt_modified':False}))
if __name__=='__main__':main()
