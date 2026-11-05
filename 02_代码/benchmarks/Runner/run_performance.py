"""Randomized paired independent-process ingestion measurements.

Input records are public-data workload replays, not new independent source samples.
"""
from pathlib import Path
import argparse,csv,json,hashlib,random,subprocess,time,datetime,os,sys,shutil
HEADERS=['record_id','dataset','source_category','field','unit','value','source_locator']
def csvread(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def csvwrite(p,rows,cols=None):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=cols or list(rows[0]));w.writeheader();w.writerows(rows)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def prepare(truth,root,protocol):
 records=csvread(truth);assert records and set(HEADERS)<=set(records[0])
 manifests={}
 for size in protocol['records_per_file']:
  d=root/f'n{size:04}';d.mkdir(parents=True,exist_ok=True);files=[];expected=[]
  for fidx in range(protocol['files_per_run']):
   rows=[]
   for idx in range(size):
    r={k:records[(fidx*size+idx)%len(records)][k] for k in HEADERS};r['record_id']=f'W{size:04}-F{fidx:02}-R{idx:04}';rows.append(r);expected.append(r)
   p=d/f'input_{fidx:02}.csv';csvwrite(p,rows,HEADERS);files.append({'path':p.name,'decimal_locale':'invariant','encoding':'utf-8'})
  manifest=d/'manifest.json';manifest.write_text(json.dumps({'files':files},indent=2),encoding='utf-8');csvwrite(d/'expected.csv',expected,HEADERS)
  manifests[size]=manifest
 return manifests
def run(args):
 protocol=json.loads(args.protocol.read_text('utf-8'));assert not args.output.exists(),'Fresh output directory required';args.output.mkdir(parents=True)
 shutil.copy2(args.protocol,args.output/'protocol.json');manifests=prepare(args.truth,args.output/'inputs',protocol)
 schedule=[{'records_per_file':n,'concurrency':c,'pair':p} for n in protocol['records_per_file'] for c in protocol['concurrency'] for p in range(1,protocol['independent_pairs_per_condition']+1)]
 rng=random.Random(protocol['random_seed']);rng.shuffle(schedule);plan=[]
 for block,s in enumerate(schedule,1):
  modes=list(protocol['modes']);rng.shuffle(modes)
  for order,mode in enumerate(modes,1):plan.append(dict(s,block=block,within_pair_order=order,mode=mode,run_id=f'b{block:03}-{mode}'))
 csvwrite(args.output/'schedule.csv',plan);rows=[];environment={'started_utc':now(),'python':sys.version,'platform':sys.platform,'random_seed':protocol['random_seed'],'executables':{m:{'path':str(getattr(args,m)),'sha256':sha(getattr(args,m))} for m in ['dynamic','static']},'protocol_sha256':sha(args.protocol),'source_truth_sha256':sha(args.truth)}
 (args.output/'environment.json').write_text(json.dumps(environment,indent=2),encoding='utf-8')
 for index,planned in enumerate(plan,1):
  n=planned['records_per_file'];d=args.output/'runs'/planned['run_id'];d.mkdir(parents=True)
  cmd=[str(getattr(args,planned['mode'])),'ingest','--input',str(manifests[n].resolve()),'--db',str((d/'records.sqlite').resolve()),'--output',str((d/'logs').resolve()),'--plugins',str(args.plugins.resolve()),'--concurrency',str(planned['concurrency'])]
  if args.python:cmd+=['--python',str(args.python)]
  started=now();tic=time.perf_counter()
  try:
   with (d/'stdout.log').open('w',encoding='utf-8') as so,(d/'stderr.log').open('w',encoding='utf-8') as se:r=subprocess.run(cmd,stdout=so,stderr=se,timeout=protocol['process_timeout_seconds']);exitcode=r.returncode;exception=''
  except Exception as e:exitcode=-1;exception=repr(e)
  wall=time.perf_counter()-tic
  row=dict(planned,started_utc=started,finished_utc=now(),exit_code=exitcode,wall_seconds=wall,expected_workload_records=n*protocol['files_per_run'],manifest_sha256=sha(manifests[n]),exception=exception)
  summary=d/'logs'/'summary.json'
  if summary.exists():row['host_summary']=str(summary.relative_to(args.output))
  else:row['host_summary']=''
  (d/'invocation.json').write_text(json.dumps({'command':cmd,'measurement':row},indent=2),encoding='utf-8');rows.append(row)
  csvwrite(args.output/'process_runs.csv',rows)
  print(f'{index}/{len(plan)} {planned["run_id"]} n={n} c={planned["concurrency"]} exit={exitcode} wall={wall:.4f}',flush=True)
 environment['finished_utc']=now();environment['runs']=len(rows);environment['nonzero_runs']=sum(r['exit_code']!=0 for r in rows);(args.output/'environment.json').write_text(json.dumps(environment,indent=2),encoding='utf-8')
 if environment['nonzero_runs']:raise SystemExit('Some measured processes failed; retained in process_runs.csv')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--truth',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--protocol',type=Path,default=Path(__file__).with_name('protocol.json'));p.add_argument('--dynamic',type=Path,required=True);p.add_argument('--static',type=Path,required=True);p.add_argument('--plugins',type=Path,required=True);p.add_argument('--python',type=Path);run(p.parse_args())
