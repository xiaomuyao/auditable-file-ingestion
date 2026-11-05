"""Independent dataset/fixture audit, not the benchmark adapter implementation."""
from pathlib import Path
import sys
sys.dont_write_bytecode=True
from decimal import Decimal
import csv,json,sqlite3,hashlib,argparse,zipfile
from openpyxl import load_workbook
from docx import Document
from pypdf import PdfReader
from prepare_data import FIELDS,canonical_decimal
def rows(p,encoding='utf-8-sig'):
 with p.open(encoding=encoding,newline='') as f:return list(csv.DictReader(f))
def parse(p,encoding='utf-8-sig'):
 if p.suffix=='.csv':return rows(p,encoding)
 if p.suffix=='.xlsx':
  wb=load_workbook(p,read_only=True,data_only=True);r=list(wb.worksheets[0].values);wb.close();return [dict(zip(r[0],v)) for v in r[1:]]
 if p.suffix=='.sqlite':
  with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as c:c.row_factory=sqlite3.Row;return [dict(x) for x in c.execute('select * from canonical_records')]
 if p.suffix=='.docx':
  rr=[[c.text for c in r.cells] for r in Document(p).tables[0].rows];return [dict(zip(rr[0],r)) for r in rr[1:]]
 if p.suffix=='.pdf':
  lines=[s.strip() for page in PdfReader(p).pages for s in (page.extract_text() or '').splitlines() if s.strip()];head=lines[0].split('|');assert head and len(head)==len(set(head));assert all(len(s.split('|'))==len(head) for s in lines[1:]);return [dict(zip(head,s.split('|'))) for s in lines[1:]]
 if p.suffix=='.json':return json.loads(p.read_text(encoding=encoding))
 raise ValueError(p)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--data-root',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();root=a.data_root;truth=rows(root/'base'/'canonical_ground_truth.csv');checks=[]
 assert len(truth)==240 and len({r['record_id'] for r in truth})==240
 for p in (root/'base'/'fixtures').iterdir():
  observed=parse(p);checks.append({'fixture':p.name,'records':len(observed),'all_seven_fields_equal':observed==truth});assert observed==truth,p
 lineage=rows(root/'base'/'source_lineage.csv');assert len(lineage)==240
 assert all(canonical_decimal(r['original_value'])==r['canonical_value'] for r in lineage)
 original_ts=(root/'raw'/'base'/'TS1.txt').read_text(encoding='utf-8-sig').splitlines();original_ai=rows(root/'raw'/'base'/'ai4i2020.csv')
 for r in lineage:
  value=original_ts[int(r['physical_row'])-1].split('\t')[0] if r['source_key']=='hydraulic' else original_ai[int(r['physical_row'])-2]['Torque [Nm]'];assert value==r['original_value']
 manifests=list((root/'base').rglob('*manifest.json'));paths=[]
 for p in manifests:
  obj=json.loads(p.read_text(encoding='utf-8'))
  for item in obj.get('files',[]):
   q=(p.parent/item['path']).resolve();assert q.exists(),(p,q);paths.append(str(q))
 report={'status':'passed','normal_format_checks':checks,'source_lineage_original_string_checks':240,'manifest_files':len(manifests),'manifest_referenced_files':len(paths),'holdout_raw_directory_exists':(root/'raw'/'holdout').exists(),'holdout_untouched':json.loads((root/'holdout'/'holdout_untouched.json').read_text(encoding='utf-8')),'xlsx_writer_validation':'Standard OOXML writer independently read with openpyxl (reading only), all seven fields equal canonical truth.','not_a_benchmark_run':True}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
