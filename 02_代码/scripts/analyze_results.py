"""Independent ingestion experiment analysis; process runs are replication units."""
from pathlib import Path
import json,csv,argparse,sqlite3,hashlib,math,statistics
from decimal import Decimal
import numpy as np
FIELDS=['record_id','dataset','source_category','field','unit','value','source_locator']
def readcsv(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def writecsv(p,rows,fieldnames=None):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fieldnames or list(rows[0]));w.writeheader();w.writerows(rows)
def boot_ci(values,seed=20261022,rep=10000):
 v=np.asarray(values,dtype=float);assert len(v)>0 and np.all(np.isfinite(v));rng=np.random.default_rng(seed);stats=np.median(v[rng.integers(0,len(v),size=(rep,len(v)))],axis=1);return tuple(float(x) for x in np.quantile(stats,[.025,.975]))
def describe(values,seed=20261022):
 v=np.asarray(values,dtype=float);low,high=boot_ci(v,seed);q=np.quantile(v,[.25,.5,.75]);return {'median':float(q[1]),'q1':float(q[0]),'q3':float(q[2]),'iqr':float(q[2]-q[0]),'ci95_low':low,'ci95_high':high}
def wilson(k,n):
 if n==0:return None,None
 z=1.959963984540054;p=k/n;den=1+z*z/n;mid=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den;return max(0,mid-half),min(1,mid+half)
def canonical_hash(row):return hashlib.sha256(json.dumps([row[k] for k in FIELDS],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def verify_database(db,expected,file_results,expected_files,host_run_id):
 with sqlite3.connect(f'file:{db.resolve().as_posix()}?mode=ro',uri=True) as c:
  c.row_factory=sqlite3.Row;rows=[dict(r) for r in c.execute('SELECT * FROM records')]
  assert not c.execute('PRAGMA foreign_key_check').fetchall(),'foreign-key violations'
  assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLite integrity failure'
  assert len(rows)==len(expected);assert {r['record_id'] for r in rows}==set(expected)
  by_record={r['record_id']:r for r in rows}
  for r in rows:
   t=expected[r['record_id']]
   for k in FIELDS:assert (Decimal(r[k])==Decimal(t[k]) if k=='value' else r[k]==t[k]),(k,r['record_id'])
   assert canonical_hash(r)==r['canonical_hash']
  duplicates=c.execute('SELECT count(*)-count(DISTINCT record_id) FROM records').fetchone()[0];assert duplicates==0
  sources=[dict(r) for r in c.execute('SELECT * FROM record_sources')];assert len(sources)==len(expected)
  audits=[dict(r) for r in c.execute('SELECT * FROM file_audit')]
  assert len(audits)==len(file_results)==len(expected_files),'audit/file cardinality mismatch'
  by_file={r['file_id']:r for r in file_results};assert len(by_file)==len(file_results),'duplicate summary file_id'
  assert {r['file_id'] for r in audits}==set(by_file),'audit identities differ from summary'
  assert {r['file_id'] for r in sources}==set(by_file),'source file identities differ from summary'
  assert len({r['input_path'] for r in file_results})==len(expected_files),'duplicate summary input path'
  for a in audits:
   fi=by_file[a['file_id']];name=fi['input_path'].replace('\\','/');truth=expected_files[name]
   assert a['run_id']==host_run_id and a['status']=='verified' and a['completed_utc']
   for key in ['input_path','input_sha256','plugin_name','plugin_version','plugin_sha256','started_utc']:
    assert a[key]==fi[key] and str(a[key]).strip(),('audit metadata',a['file_id'],key)
   assert a['error_code']=='' and not a['quarantine_path']
   assert int(a['expected_rows'])==fi['nrows']==len(truth)
   assert int(a['inserted_rows'])==fi['inserted_rows']==len(truth) and int(a['idempotent_rows'])==fi['idempotent_rows']==0
   assert 0<=float(a['elapsed_ms'])<=fi['latency_ms']+1e-7
   ss=[r for r in sources if r['file_id']==a['file_id']]
   assert len(ss)==len(truth) and {r['record_id'] for r in ss}==set(truth),('per-file sources',name)
   for source in ss:
    record=by_record[source['record_id']]
    assert source['canonical_hash']==record['canonical_hash']==canonical_hash(record)
    assert source['source_locator']==record['source_locator']==truth[record['record_id']]['source_locator']
  provenance=c.execute('SELECT count(DISTINCT r.record_id) FROM records r JOIN record_sources s ON s.record_id=r.record_id AND s.canonical_hash=r.canonical_hash AND s.source_locator=r.source_locator JOIN file_audit a ON a.file_id=s.file_id').fetchone()[0];assert provenance==len(expected)
 return len(rows)
def performance(root,out):
 process=readcsv(root/'process_runs.csv');schedule=readcsv(root/'schedule.csv')
 protocol=json.loads((root/'protocol.json').read_text('utf-8'));rows=[];verified=0;problems=[]
 planned=len(protocol['records_per_file'])*len(protocol['concurrency'])*protocol['independent_pairs_per_condition']*len(protocol['modes'])
 attempts=[dict(r,attempt_index=i+1,validation_status='not_yet_validated',validation_error='') for i,r in enumerate(process)]
 writecsv(out/'performance_attempts.csv',attempts,list(process[0])+['attempt_index','validation_status','validation_error'] if process else ['attempt_index','run_id','validation_status','validation_error'])
 (out/'performance_failure_ledger.json').write_text(json.dumps({'status':'validation_pending','planned_attempts':planned,'observed_attempts':len(process),'all_observed_attempts_csv':'performance_attempts.csv'},indent=2),encoding='utf-8')
 try:
  assert planned==216 and protocol['independent_pairs_per_condition']==12
  assert len(process)==len(schedule)==planned,'incomplete or extra process attempts'
  assert len({r['run_id'] for r in schedule})==len(schedule),'duplicate scheduled run_id'
  assert len({r['run_id'] for r in process})==len(process),'duplicate observed run_id'
  assert [r['run_id'] for r in process]==[r['run_id'] for r in schedule],'actual order differs from randomized schedule'
  pair_blocks=[]
  for n in protocol['records_per_file']:
   for concurrency in protocol['concurrency']:
    for pair in range(1,protocol['independent_pairs_per_condition']+1):
     cell=[r for r in schedule if int(r['records_per_file'])==n and int(r['concurrency'])==concurrency and int(r['pair'])==pair]
     assert len(cell)==2 and {r['mode'] for r in cell}=={'dynamic','static'},('planned pair membership',n,concurrency,pair)
     assert len({r['block'] for r in cell})==1 and {int(r['within_pair_order']) for r in cell}=={1,2}
     indices=[schedule.index(r) for r in cell];assert indices[1]-indices[0]==1 and int(cell[0]['within_pair_order'])==1,'paired processes not adjacent/in order'
     pair_blocks.append(cell[0]['block'])
  assert len(set(pair_blocks))==len(pair_blocks),'block reused for different process pairs'
 except Exception as e:problems.append({'scope':'schedule','error':type(e).__name__+':'+str(e)})
 schedule_by_id={r['run_id']:r for r in schedule};expected_by_n={};expected_files_by_n={};manifest_hashes={}
 try:
  for n in protocol['records_per_file']:
   inputs=root/'inputs'/f'n{n:04}';raw=readcsv(inputs/'expected.csv');expected_by_n[n]={r['record_id']:r for r in raw};assert len(raw)==len(expected_by_n[n])
   manifest=json.loads((inputs/'manifest.json').read_text('utf-8-sig'));manifest_hashes[n]=hashlib.sha256((inputs/'manifest.json').read_bytes()).hexdigest();by_file={}
   for descriptor in manifest['files']:
    name=descriptor['path'].replace('\\','/');rr=readcsv(inputs/name);by_file[name]={r['record_id']:r for r in rr};assert len(rr)==len(by_file[name])==n
   assert len(by_file)==protocol['files_per_run'] and sum(map(len,by_file.values()))==len(expected_by_n[n])
   assert set().union(*(set(rr) for rr in by_file.values()))==set(expected_by_n[n])
   expected_files_by_n[n]=by_file
 except Exception as e:problems.append({'scope':'input_truth','error':type(e).__name__+':'+str(e)})
 for i,r in enumerate(process):
  try:
   assert r['run_id'] in schedule_by_id,'unscheduled attempt'
   for key in ['records_per_file','concurrency','pair','block','within_pair_order','mode','run_id']:assert r[key]==schedule_by_id[r['run_id']][key],('schedule metadata mismatch',key)
   assert int(r['exit_code'])==0 and not r.get('exception',''),'nonzero exit or runner exception; raw attempt retained'
   n=int(r['records_per_file']);c=int(r['concurrency']);s=json.loads((root/r['host_summary']).read_text('utf-8-sig'));expected=expected_by_n[n]
   assert s['mode']==r['mode'] and s['concurrency']==c,'Host mode/concurrency mismatch'
   assert s['manifest_sha256']==r['manifest_sha256']==manifest_hashes[n]
   assert int(r['expected_workload_records'])==len(expected)==n*protocol['files_per_run']
   assert s['files_attempted']==s['files_verified']==protocol['files_per_run'] and s['files_failed']==s['files_quarantined']==0
   assert s['record_count']==s['records_inserted']==s['records_submitted']==len(expected) and s['records_idempotent']==0
   assert s['provenance_complete_records']==len(expected) and s['audit_db_complete_files']==protocol['files_per_run']
   assert math.isfinite(float(r['wall_seconds'])) and float(r['wall_seconds'])>0 and s['duration_ms']>0
   assert math.isclose(s['throughput_records_per_second'],len(expected)/(s['duration_ms']/1000),rel_tol=1e-9)
   assert math.isclose(s['cpu_percent_normalized'],s['total_cpu_ms']/s['duration_ms']/s['logical_processors']*100,rel_tol=1e-9,abs_tol=1e-9)
   d=root/'runs'/r['run_id'];verified+=verify_database(d/'records.sqlite',expected,s['results'],expected_files_by_n[n],s['run_id'])
   lat=[x['latency_ms'] for x in s['results']];assert len(lat)==protocol['files_per_run'] and all(math.isfinite(x) and x>=0 for x in lat)
   for p,k in [(.5,'p50_file_latency_ms'),(.95,'p95_file_latency_ms'),(.99,'p99_file_latency_ms')]:assert math.isclose(float(np.quantile(lat,p)),s[k],rel_tol=1e-9,abs_tol=1e-8)
   for fi in s['results']:
    f=root/'inputs'/f'n{n:04}'/fi['input_path'];assert hashlib.sha256(f.read_bytes()).hexdigest()==fi['input_sha256']
    assert fi['status']=='verified' and fi['audit_db_complete'] is True
   rows.append({'run_id':r['run_id'],'block':int(r['block']),'pair':int(r['pair']),'order':int(r['within_pair_order']),'mode':r['mode'],'records_per_file':n,'workload_records':len(expected),'concurrency':c,'wall_seconds':float(r['wall_seconds']),'host_seconds':s['duration_ms']/1000,'wall_throughput_rps':len(expected)/float(r['wall_seconds']),'host_throughput_rps':s['throughput_records_per_second'],'discovery_ms':s['discovery_ms'],'p50_file_latency_ms':s['p50_file_latency_ms'],'p95_file_latency_ms':s['p95_file_latency_ms'],'p99_file_latency_ms':s['p99_file_latency_ms'],'cpu_percent_normalized':s['cpu_percent_normalized'],'total_cpu_ms':s['total_cpu_ms'],'peak_memory_mib':s['peak_working_set_bytes']/1048576,'files_verified':s['files_verified'],'records_verified':len(expected)})
   attempts[i]['validation_status']='validated'
  except Exception as e:
   attempts[i]['validation_status']='failed';attempts[i]['validation_error']=type(e).__name__+':'+str(e);problems.append({'scope':'attempt','run_id':r.get('run_id',''),'attempt_index':i+1,'error':attempts[i]['validation_error']})
 writecsv(out/'performance_attempts.csv',attempts,list(process[0])+['attempt_index','validation_status','validation_error'] if process else ['attempt_index','run_id','validation_status','validation_error'])
 ledger={'status':'blocked' if problems else 'passed','planned_attempts':planned,'observed_attempts':len(process),'validated_attempts':len(rows),'failed_validation_attempts':sum(r['validation_status']=='failed' for r in attempts),'all_observed_attempts_csv':'performance_attempts.csv','problems':problems,'policy':'All observed attempts retained. Any execution/verification/schedule failure blocks the paired comparison; no replacement runs or successful-only comparison.'}
 (out/'performance_failure_ledger.json').write_text(json.dumps(ledger,indent=2),encoding='utf-8')
 if problems:
  report=dict(ledger,comparison_performed=False)
  (out/'performance_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return report
 groups=[];pairs=[];overheads=[]
 metrics=['wall_seconds','host_seconds','wall_throughput_rps','host_throughput_rps','discovery_ms','p50_file_latency_ms','p95_file_latency_ms','p99_file_latency_ms','cpu_percent_normalized','total_cpu_ms','peak_memory_mib']
 for n in protocol['records_per_file']:
  for c in protocol['concurrency']:
   for mode in ['dynamic','static']:
    rr=[r for r in rows if r['records_per_file']==n and r['concurrency']==c and r['mode']==mode];assert len(rr)==12
    g={'records_per_file':n,'workload_records':n*12,'concurrency':c,'mode':mode,'n_independent_processes':len(rr)}
    for j,m in enumerate(metrics):g.update({m+'_'+k:v for k,v in describe([r[m] for r in rr],20261022+j).items()})
    groups.append(g)
   cell=[]
   for p in range(1,13):
    members=[r for r in rows if r['records_per_file']==n and r['concurrency']==c and r['pair']==p];assert len(members)==2
    rr={r['mode']:r for r in members};assert set(rr)=={'dynamic','static'} and rr['dynamic']['block']==rr['static']['block'] and {rr['dynamic']['order'],rr['static']['order']}=={1,2}
    diff=(rr['dynamic']['wall_seconds']/rr['static']['wall_seconds']-1)*100;hostdiff=(rr['dynamic']['host_seconds']/rr['static']['host_seconds']-1)*100
    row={'records_per_file':n,'workload_records':n*12,'concurrency':c,'pair':p,'block':rr['dynamic']['block'],'dynamic_first':rr['dynamic']['order']==1,'relative_wall_overhead_percent':diff,'relative_host_overhead_percent':hostdiff,'dynamic_wall_seconds':rr['dynamic']['wall_seconds'],'static_wall_seconds':rr['static']['wall_seconds']};pairs.append(row);cell.append(diff)
   overheads.append(dict(records_per_file=n,workload_records=n*12,concurrency=c,n_pairs=12,**describe(cell)))
 writecsv(out/'process_metrics.csv',rows);writecsv(out/'performance_groups.csv',groups);writecsv(out/'paired_overheads.csv',pairs);writecsv(out/'overhead_summary.csv',overheads)
 report={'status':'passed','comparison_performed':True,'independent_processes':len(rows),'randomized_pairs':len(pairs),'conditions':len(overheads),'verified_canonical_records_across_runs':verified,'failures_excluded':0,'all_attempts_and_failures_retained':True,'bootstrap_repetitions':10000,'bootstrap_seed_base':20261022,'bootstrap_statistic':'median','interval':'95% percentile; paired ratios resampled at process-pair level; marginal metrics at process level','primary_endpoint':'paired relative whole-process wall-time overhead','scope':'12 controlled CSV replay files, shared single host, identical parser source/backend; not pure reflection instruction microbenchmark or saturation test'}
 (out/'performance_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return report
def correctness(directories,out):
 files=[];summ=[];failures=[]
 for d in directories:
  if not d.exists():continue
  rr=readcsv(d/'file_correctness.csv');files+=rr
  failures.extend(dict(r,source_directory=str(d)) for r in rr if r.get('oracle_pass')!='True' or r.get('provenance_complete')!='True' or (r['expected_outcome']=='reject_file' and (r['observed_status']!='quarantined' or r.get('quarantined_copy')!='True')) or (r['expected_outcome'] in {'accept','idempotent_no_new_rows'} and r['observed_status']!='verified'))
  part=rr[0]['partition'];source=json.loads((d/'correctness_summary.json').read_text('utf-8'))
  for fmt in ['csv','xlsx','sqlite','docx','pdf','json']:
   ff=[r for r in rr if r['format']==fmt]
   if not ff:continue
   good=[r for r in ff if r['expected_outcome'] in {'accept','idempotent_no_new_rows'}];bad=[r for r in ff if r['expected_outcome']=='reject_file'];assert len(good)+len(bad)==len(ff),'unrecognized registered outcome'
   k=sum(r['observed_status']=='verified' and r.get('oracle_pass')=='True' and r.get('provenance_complete')=='True' for r in good)
   kb=sum(r['observed_status']=='quarantined' and r.get('oracle_pass')=='True' and r.get('provenance_complete')=='True' and r.get('quarantined_copy')=='True' for r in bad)
   lo,hi=wilson(k,len(good));lb,hb=wilson(kb,len(bad))
   summ.append({'partition':part,'format':fmt,'valid_files':len(good),'valid_accepted':k,'valid_acceptance_rate':k/len(good) if good else '', 'valid_wilson95_low':lo,'valid_wilson95_high':hi,'invalid_files':len(bad),'invalid_detected':kb,'detection_rate':kb/len(bad) if bad else '', 'detection_wilson95_low':lb,'detection_wilson95_high':hb,'field_comparisons':sum(int(r['fields_compared']) for r in ff),'field_matches':sum(int(r['fields_matching']) for r in ff),'provenance_complete_files':sum(r['provenance_complete']=='True' for r in ff),'oracles_passed':sum(r['oracle_pass']=='True' for r in ff),'files_tested':len(ff)})
 writecsv(out/'correctness_by_format.csv',summ)
 report={'status':'blocked' if failures else 'passed','files_observed':len(files),'oracle_or_provenance_failures':len(failures),'failures':failures,'invalid_detection_definition':'quarantined AND oracle_pass AND provenance_complete AND original-byte quarantine copy; generic database/harness failure is not correct detection','interval_boundary':'Wilson intervals describe this fixed controlled file-test set; variants share canonical records and are not a random sample of all instruments/formats.'}
 (out/'correctness_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return summ
def faults(root,out):
 trials=json.loads((root/'all_trials.json').read_text('utf-8'));groups=[]
 keys=[('truncated_file',''),('missing_fields',''),('plugin_exception',''),('duplicate_replay',''),('database_lock',''),('transaction_interruption',''),('process_termination','hold_before_commit'),('process_termination','hold_after_commit')]
 try:
  assert len(trials)==80,'formal fault analysis requires all 80 registered trials, not pilot data'
  assert len({r['case_id'] for r in trials})==80,'duplicate fault case_id'
  assert {(r['fault_class'],r.get('fault_stage','')) for r in trials}==set(keys),'unexpected/missing fault subcondition'
  assert len({(r['fault_class'],r.get('fault_stage',''),int(r['trial'])) for r in trials})==80,'duplicate trial identity'
  for kind,stage in keys:
   rr=[r for r in trials if r['fault_class']==kind and r.get('fault_stage','')==stage]
   assert len(rr)==10 and {int(r['trial']) for r in rr}==set(range(1,11)),('subcondition not 10 registered repeats',kind,stage)
   assert all(r.get('planned') is True for r in rr),'unplanned replacement fault trial'
 except Exception as e:
  report={'status':'blocked','n_trials':len(trials),'error':type(e).__name__+':'+str(e),'raw_trials_preserved':True,'comparison_performed':False}
  (out/'fault_analysis.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return report
 for index,(kind,stage) in enumerate(keys):
  rr=[r for r in trials if r['fault_class']==kind and r.get('fault_stage','')==stage];n=len(rr);k=sum(r.get('passed',False) for r in rr);lo,hi=wilson(k,n)
  loss=[r['committed_loss'] for r in rr if r.get('committed_loss') is not None];dups=[r['duplicate_rows'] for r in rr if r.get('duplicate_rows') is not None]
  elapsed=[r['elapsed_ms'] for r in rr if r.get('elapsed_ms') is not None];recovery=[r['recover_elapsed_ms'] for r in rr if r.get('recover_elapsed_ms') is not None]
  event_assessed=[r for r in rr if r.get('audit_events_required') is not None and r.get('audit_events_observed') is not None]
  required=sum(r['audit_events_required'] for r in event_assessed);observed=sum(r['audit_events_observed'] for r in event_assessed)
  check_assessed=[r for r in rr if r.get('audit_checks_required') is not None and r.get('audit_checks_passed') is not None]
  checks_required=sum(r['audit_checks_required'] for r in check_assessed);checks_passed=sum(r['audit_checks_passed'] for r in check_assessed)
  g={'fault_class':kind,'fault_stage':stage,'n_trials':n,'expected_terminal_achieved':k,'proportion':k/n,'wilson95_low':lo,'wilson95_high':hi,'committed_loss_assessed_trials':len(loss),'committed_loss':sum(loss) if len(loss)==n else 'not_fully_assessed','duplicate_rows_assessed_trials':len(dups),'duplicate_rows':sum(dups) if len(dups)==n else 'not_fully_assessed','audit_events_assessed_trials':len(event_assessed),'audit_events_observed':observed,'audit_events_required':required,'audit_completeness':observed/required if len(event_assessed)==n and required else 'not_fully_assessed','audit_checks_assessed_trials':len(check_assessed),'audit_checks_passed':checks_passed,'audit_checks_required':checks_required,'audit_checks_completeness':checks_passed/checks_required if len(check_assessed)==n and checks_required else 'not_fully_assessed','harness_errors':sum('harness_error' in r for r in rr),'recovery_timed_trials':len(recovery)}
  for label,values in [('whole_case_ms',elapsed),('recovery_ms',recovery)]:
   if values:g.update({label+'_'+key:v for key,v in describe(values,20261030+index).items()})
   else:g.update({label+'_'+key:None for key in ['median','q1','q3','iqr','ci95_low','ci95_high']})
  groups.append(g)
 writecsv(out/'fault_summary.csv',groups)
 report={'status':'passed' if all(r.get('passed') is True for r in trials) else 'completed_with_failures','n_trials':len(trials),'expected_terminal_achieved':sum(r.get('passed',False) for r in trials),'subconditions':len(keys),'trials_per_subcondition':10,'unique_trial_identity_verified':True,'unit':'independently initialized fault trial; restarted processes are steps within the same trial','interval':'Wilson 95% for prespecified binary terminal outcomes; descriptive fixed-injection coverage, not production reliability','source_unchanged_assessed_trials':sum('source_unchanged' in r for r in trials),'no_source_repairs':all(r.get('source_unchanged') is True for r in trials),'permanent_rejections_have_recovery_time':False,'time_metrics_not_pooled_across_different_definitions':True}
 (out/'fault_analysis.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--performance',type=Path);p.add_argument('--base',type=Path);p.add_argument('--late',type=Path);p.add_argument('--holdout',type=Path);p.add_argument('--faults',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 result={};blocked=False
 if a.performance:
  result['performance']=performance(a.performance,a.out);blocked|=result['performance'].get('status')=='blocked'
 dirs=[q for q in [a.base,a.late,a.holdout] if q]
 if dirs:
  result['correctness']=correctness(dirs,a.out);blocked|=json.loads((a.out/'correctness_verification.json').read_text('utf-8'))['status']=='blocked'
 if a.faults:
  result['faults']=faults(a.faults,a.out);blocked|=result['faults'].get('status')=='blocked'
 (a.out/'analysis_summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
 raise SystemExit(2 if blocked else 0)
