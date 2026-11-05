"""Independent public-fixture oracle for the actual DLL ingestion pipeline."""
from pathlib import Path
from decimal import Decimal
import argparse,csv,json,hashlib,sqlite3,subprocess,datetime,time,sys
FIELDS=['record_id','dataset','source_category','field','unit','value','source_locator']
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def readcsv(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def writecsv(p,rows,fields=None):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)
def freeze_check(manifest,root):
 obj=json.loads(manifest.read_text('utf-8'))
 for r in obj['files']:assert sha(root/r['path'])==r['sha256'],r['path']
 return obj
def query(db,sql,params=()):
 with sqlite3.connect(f'file:{db.resolve().as_posix()}?mode=ro',uri=True) as c:c.row_factory=sqlite3.Row;return [dict(r) for r in c.execute(sql,params)]
def run(a):
 assert not a.output.exists(),'Refuse existing result directory';a.output.mkdir(parents=True)
 partition=a.partition;source=a.data/partition;truth=readcsv(source/'canonical_ground_truth.csv');oracle={r['record_id']:r for r in truth};assert len(oracle)==len(truth)
 frozen=freeze_check(a.freeze,a.code)
 receipt={'partition':partition,'started_at_utc':now(),'freeze_manifest_sha256':sha(a.freeze),'frozen_at_utc':frozen['frozen_at_utc'],'truth_sha256':sha(source/'canonical_ground_truth.csv'),'source_records':len(truth),'adapter_tuning_permitted':False}
 if partition=='holdout':
  gate=source/'first_evaluation_receipt.json'
  if gate.exists() and not a.reproduction:raise RuntimeError('Holdout already evaluated; no adaptive rerun allowed')
  if not a.reproduction:gate.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
 (a.output/'evaluation_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
 manifests=sorted({p for p in source.rglob('*manifest.json') if p.name!='data_manifest.json'})
 manifests=[p for p in manifests if p.name=='manifest.json' or p.parent.name=='truncated']
 rows=[];details=[];cases=[]
 for index,manifest in enumerate(manifests,1):
  obj=json.loads(manifest.read_text('utf-8'));files=obj.get('files')
  if not files:continue
  case=obj.get('case',manifest.parent.name);caseid=f'{index:03}_{case}_{manifest.stem}';out=a.output/'runs'/caseid;out.mkdir(parents=True)
  expected=obj.get('expected_file_outcomes',[obj.get('expected_outcome','accept')]*len(files));db=out/'records.sqlite';logs=out/'logs'
  cmd=[str(a.host),'ingest','--input',str(manifest.resolve()),'--db',str(db.resolve()),'--output',str(logs.resolve()),'--plugins',str(a.plugins.resolve()),'--concurrency','1','--python',str(a.python)]
  tic=time.perf_counter()
  with (out/'stdout.log').open('w',encoding='utf-8') as so,(out/'stderr.log').open('w',encoding='utf-8') as se:proc=subprocess.run(cmd,stdout=so,stderr=se,timeout=180)
  wall=time.perf_counter()-tic
  summary_path=logs/'summary.json'
  if not summary_path.exists():
   cases.append({'case_id':caseid,'case':case,'exit_code':proc.returncode,'wall_seconds':wall,'summary_available':False,'expected_final_records':obj.get('expected_final_unique_rows',0),'actual_records':None,'oracle_pass':False});continue
  summary=json.loads(summary_path.read_text('utf-8-sig'));results=summary['results'];assert len(results)==len(files)
  audits=query(db,'SELECT * FROM file_audit');auditmap={r['file_id']:r for r in audits}
  all_records=query(db,'SELECT * FROM records');dbmap={r['record_id']:r for r in all_records}
  for i,(fi,res,exp) in enumerate(zip(files,results,expected)):
   inputpath=(manifest.parent/fi['path']).resolve();fileid=res['file_id'];status=res['status'];want_accept=exp in {'accept','idempotent_no_new_rows'}
   sources=query(db,'SELECT r.*,s.canonical_hash AS source_hash FROM record_sources s JOIN records r ON r.record_id=s.record_id WHERE s.file_id=?',(fileid,));observed_ids={r['record_id'] for r in sources};audit=auditmap.get(fileid,{})
   matches=0;comparisons=0;errors=[]
   for r in sources:
    gt=oracle.get(r['record_id'])
    if gt is None:errors.append('unexpected_record:'+r['record_id']);continue
    for k in FIELDS:
     same=(Decimal(r[k])==Decimal(gt[k])) if k=='value' else r[k]==gt[k];comparisons+=1;matches+=same
     details.append({'partition':partition,'case_id':caseid,'format':inputpath.suffix[1:],'file_id':fileid,'record_id':r['record_id'],'field':k,'truth':gt[k],'readback':r[k],'match':same,'absolute_error':str(abs(Decimal(r[k])-Decimal(gt[k]))) if k=='value' else ''})
   metadata_ok=all(str(audit.get(k,'')) not in {'','UNAVAILABLE'} for k in ['input_sha256','input_path','plugin_name','plugin_version','plugin_sha256','started_utc','completed_utc']) and audit.get('input_sha256')==sha(inputpath)
   source_ok=all(r['source_locator'] and r['canonical_hash']==r['source_hash'] for r in sources)
   accepted=status=='verified';expected_rows=10 if exp=='idempotent_no_new_rows' else len(truth)
   good=(accepted and len(sources)==expected_rows and matches==comparisons and not errors and metadata_ok and source_ok) if want_accept else (not accepted and len(sources)==0 and metadata_ok)
   if exp=='idempotent_no_new_rows':good=good and res['inserted_rows']==0 and res['idempotent_rows']==10
   rows.append({'partition':partition,'case_id':caseid,'case':case,'format':inputpath.suffix[1:],'input_file':inputpath.relative_to(a.data.resolve()).as_posix(),'expected_outcome':exp,'observed_status':status,'input_rows':res['nrows'],'stored_rows_for_file':len(sources),'fields_compared':comparisons,'fields_matching':matches,'inserted_rows':res['inserted_rows'],'idempotent_rows':res['idempotent_rows'],'provenance_complete':metadata_ok and source_ok,'quarantined_copy':bool(res.get('quarantine_path')),'error_code':res.get('error_code',''),'oracle_pass':good,'file_latency_ms':res['latency_ms']})
  wanted=obj.get('expected_final_unique_rows',len(truth) if any(x in {'accept','idempotent_no_new_rows'} for x in expected) else 0)
  consistent=len(dbmap)==wanted and all(rid in oracle and all(Decimal(r['value'])==Decimal(oracle[rid]['value']) if k=='value' else r[k]==oracle[rid][k] for k in FIELDS) for rid,r in dbmap.items())
  case_rows=[r for r in rows if r['case_id']==caseid];cases.append({'case_id':caseid,'case':case,'exit_code':proc.returncode,'wall_seconds':wall,'summary_available':True,'expected_final_records':wanted,'actual_records':len(dbmap),'oracle_pass':consistent and all(r['oracle_pass'] for r in case_rows)})
  (out/'invocation.json').write_text(json.dumps({'command':cmd,'manifest_sha256':sha(manifest),'expected':expected},indent=2),encoding='utf-8')
  print(f'{partition} {index}/{len(manifests)} {caseid} files={len(files)} oracle={cases[-1]["oracle_pass"]}',flush=True)
 writecsv(a.output/'file_correctness.csv',rows);writecsv(a.output/'field_comparisons.csv',details,FIELDS if not details else None);writecsv(a.output/'case_results.csv',cases)
 report={'partition':partition,'dataset_records':len(truth),'cases':len(cases),'files':len(rows),'cases_passed':sum(c['oracle_pass'] for c in cases),'file_oracles_passed':sum(r['oracle_pass'] for r in rows),'valid_files':sum(r['expected_outcome'] in {'accept','idempotent_no_new_rows'} for r in rows),'valid_files_accepted':sum(r['expected_outcome'] in {'accept','idempotent_no_new_rows'} and r['observed_status']=='verified' for r in rows),'invalid_files':sum(r['expected_outcome']=='reject_file' for r in rows),'invalid_files_detected':sum(r['expected_outcome']=='reject_file' and r['observed_status']!='verified' for r in rows),'field_comparisons':len(details),'field_matches':sum(r['match'] for r in details),'provenance_complete_files':sum(r['provenance_complete'] for r in rows),'finished_at_utc':now(),'unchanged_frozen_code':True}
 freeze_check(a.freeze,a.code);(a.output/'correctness_summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 if partition=='holdout' and not a.reproduction:
  receipt.update(finished_at_utc=now(),result_summary=report);(source/'first_evaluation_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
 print(json.dumps(report,indent=2))
 if report['cases_passed']!=len(cases):raise SystemExit('Some prespecified correctness expectations failed; all observations retained')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--partition',choices=['base','late_json','holdout'],required=True);p.add_argument('--host',type=Path,required=True);p.add_argument('--plugins',type=Path,required=True);p.add_argument('--python',type=Path,required=True);p.add_argument('--freeze',type=Path,required=True);p.add_argument('--code',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--reproduction',action='store_true');run(p.parse_args())
