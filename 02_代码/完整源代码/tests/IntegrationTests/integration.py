"""Independent-process, SQLite-readback integration checks on base data only."""
import argparse,csv,json,sqlite3,subprocess,sys,time,hashlib
from pathlib import Path

FIELDS=['record_id','dataset','source_category','field','unit','value','source_locator']

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--bin',type=Path);p.add_argument('--python',default=sys.executable);a=p.parse_args()
 code=Path(__file__).resolve().parents[2];binary=a.bin.resolve() if a.bin else code/'bin';base=a.data.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 truth={r['record_id']:tuple(r[k] for k in FIELDS) for r in csv.DictReader((base/'canonical_ground_truth.csv').open(encoding='utf-8-sig'))}
 expected=json.loads((base/'expected_outcomes.json').read_text(encoding='utf-8-sig'))['cases'];reports=[]
 manifests=[base/'manifest.json']+sorted((base/'variants').glob('*/manifest.json'))
 described={(m.parent/f['path']).resolve() for m in manifests for f in json.loads(m.read_text(encoding='utf-8-sig'))['files']}
 missing=[r for r in expected if (base.parent/r['relative_path']).resolve() not in described]
 for case in sorted({r['case'] for r in missing}):
  group=[r for r in missing if r['case']==case];generated=out/'generated-manifests';generated.mkdir(exist_ok=True)
  manifest=generated/(case+'.json');manifest.write_text(json.dumps({'case':case,'files':[{'path':str((base.parent/r['relative_path']).resolve()),'decimal_locale':r['decimal_locale'],'encoding':r['encoding'],'delimiter':','} for r in group],'expected_final_unique_rows':0 if all(r['expected_outcome']=='reject_file' for r in group) else len(truth)}),encoding='utf-8');manifests.append(manifest)
 for mode,exe in [('dynamic','Host.exe'),('static','Baseline.exe')]:
  for manifest in manifests:
   spec=json.loads(manifest.read_text(encoding='utf-8-sig'));case=spec.get('case','normal');d=out/mode/case;d.mkdir(parents=True)
   command=[str(binary/exe),'ingest','--input',str(manifest),'--db',str(d/'records.sqlite'),'--output',str(d),'--python',a.python,'--pdf-bridge',str(code/'scripts/pdf_bridge.py'),'--concurrency','1']
   began=time.perf_counter();proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace');(d/'stdout.txt').write_text(proc.stdout,encoding='utf-8');(d/'stderr.txt').write_text(proc.stderr,encoding='utf-8')
   summary=json.loads((d/'summary.json').read_text(encoding='utf-8-sig'));observed=summary['results'];assert len(observed)==len(spec['files'])
   outcomes=[]
   for i,(descriptor,result) in enumerate(zip(spec['files'],observed)):
    full=(manifest.parent/descriptor['path']).resolve();entry=next(r for r in expected if (base.parent/r['relative_path']).resolve()==full)
    reject=entry['expected_outcome']=='reject_file';assert result['status']==('quarantined' if reject else 'verified'),(mode,case,i,result['status'],result['error_code'])
    assert result['input_sha256']==hashlib.sha256(full.read_bytes()).hexdigest();assert result['audit_db_complete']
    if reject: assert (d/result['quarantine_path']).read_bytes()==full.read_bytes()
    outcomes.append(result['status'])
   db=sqlite3.connect(d/'records.sqlite');rows=db.execute('SELECT '+','.join(FIELDS)+' FROM records ORDER BY record_id').fetchall();audit=db.execute('SELECT status FROM file_audit').fetchall();sources=db.execute('SELECT count(*) FROM record_sources').fetchone()[0];db.close()
   assert all(tuple(row)==truth[row[0]] for row in rows),(mode,case,'truth mismatch')
   if 'expected_final_unique_rows' in spec: assert len(rows)==spec['expected_final_unique_rows'],(mode,case,len(rows),spec['expected_final_unique_rows'])
   assert len(audit)==len(spec['files']);assert len(rows)==summary['record_count'];assert summary['provenance_completeness']==1
   assert proc.returncode==(2 if 'quarantined' in outcomes else 0),(mode,case,proc.returncode)
   reports.append({'mode':mode,'case':case,'files':len(observed),'records':len(rows),'sources':sources,'statuses':outcomes,'exit_code':proc.returncode,'wall_ms':(time.perf_counter()-began)*1000,'status':'passed'})
 (out/'integration_report.json').write_text(json.dumps({'status':'passed','cases':reports,'process_runs':len(reports),'file_attempts':sum(x['files'] for x in reports)},indent=2),encoding='utf-8')
 print(json.dumps({'status':'passed','process_runs':len(reports),'file_attempts':sum(x['files'] for x in reports)}))

if __name__=='__main__':main()

