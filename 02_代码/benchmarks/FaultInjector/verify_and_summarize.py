"""Read-only independent verification and descriptive fault summaries.

Expected final rows are reconstructed from retained guard and accepted input
CSV files, rather than trusting the harness's expected-hash JSON or pass flag.
The original trial outputs are never changed.
"""
import argparse,csv,hashlib,json,math,sqlite3,statistics,unicodedata
from decimal import Decimal
from pathlib import Path

FIELDS=['record_id','dataset','source_category','field','unit','value','source_locator']
TERMINAL={'verified','quarantined','failed','interrupted_uncommitted','verified_reconciled'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,o):Path(p).write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')
def values(r):
    row=[unicodedata.normalize('NFC',r[k].strip()) for k in FIELDS]
    row[5]=format(Decimal(row[5]).normalize(),'f')
    if Decimal(row[5])==0:row[5]='0'
    return row
def digest(r):return hashlib.sha256(json.dumps(values(r),ensure_ascii=True,separators=(',',':')).encode()).hexdigest()
def read_csv(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def csv_output(p,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with Path(p).open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def event_list(case):
    es=[];bad=[]
    for p in case.rglob('events.jsonl'):
        for n,line in enumerate(p.read_text(encoding='utf-8').splitlines(),1):
            try:es.append(json.loads(line))
            except Exception:bad.append([str(p.relative_to(case)),n])
    return es,bad
def row_check(rows,expected):
    actual={r['record_id']:r['canonical_hash'] for r in rows}
    return {'row_count':len(rows),'expected_count':len(expected),'row_set_equal':actual==expected,'stored_vs_recomputed_hash_equal':all(digest(r)==r['canonical_hash'] for r in rows),'duplicate_rows':len(rows)-len(actual),'committed_missing_or_changed':sum(actual.get(k)!=v for k,v in expected.items())}
def verify(case,artifacts):
    reported=load(case/'trial_result.json');checks={};issues=[]
    fixture=read_csv(case/'guard.csv')+read_csv(case/('healthy.csv' if (case/'healthy.csv').is_file() else 'input.csv'))
    expected={r['record_id']:digest(r) for r in fixture}
    con=sqlite3.connect((case/'records.sqlite').resolve().as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
    try:
        con.execute('PRAGMA query_only=ON');rows=[dict(r) for r in con.execute('SELECT * FROM records')];audits=[dict(r) for r in con.execute('SELECT * FROM file_audit')];sources=[dict(r) for r in con.execute('SELECT * FROM record_sources')]
        checks['integrity_ok']=con.execute('PRAGMA integrity_check').fetchone()[0]=='ok';checks['foreign_keys_ok']=not list(con.execute('PRAGMA foreign_key_check'))
    finally:con.close()
    rowstats=row_check(rows,expected);checks['final_expected_rows']=rowstats['row_set_equal'];checks['final_hashes']=rowstats['stored_vs_recomputed_hash_equal'];checks['unique_rows']=rowstats['duplicate_rows']==0
    es,malformed=event_list(case);checks['jsonl_complete_lines']=not malformed
    observed=0;required=2*len(audits)
    for a in audits:
        source=case/a['input_path'];checks['source_hash:'+a['file_id']]=source.is_file() and sha(source)==a['input_sha256']
        checks['plugin_hash:'+a['file_id']]=a['plugin_sha256'] in artifacts
        checks['audit_terminal:'+a['file_id']]=a['status'] in TERMINAL and bool(a['completed_utc'])
        intent=any(e.get('event_type')=='intent' and e.get('file_id')==a['file_id'] for e in es)
        terminal=any(e.get('event_type')=='terminal' and e.get('result',{}).get('file_id')==a['file_id'] and e['result'].get('status')==a['status'] for e in es)
        reconcile=any(e.get('event_type')=='reconcile' and e.get('file_id')==a['file_id'] and e.get('status')==a['status'] for e in es)
        checks['intent:'+a['file_id']]=intent;checks['completion:'+a['file_id']]=terminal or reconcile;observed+=intent+(terminal or reconcile)
    audit_ids={a['file_id'] for a in audits};rowhash={r['record_id']:r['canonical_hash'] for r in rows}
    checks['lineage_referential']=all(s['file_id'] in audit_ids and rowhash.get(s['record_id'])==s['canonical_hash'] for s in sources)
    kind=reported['fault_class'];stage=reported['fault_stage'];guardexpected={r['record_id']:digest(r) for r in read_csv(case/'guard.csv')}
    committed_before_fault=expected if kind=='duplicate_replay' or (kind=='process_termination' and stage=='hold_after_commit') else guardexpected
    committed_loss=sum(rowhash.get(k)!=v for k,v in committed_before_fault.items());checks['committed_records_preserved']=committed_loss==0
    if kind in {'truncated_file','missing_fields','plugin_exception'}:
        summary=load(case/'fault_run/summary.json');bad,good=summary['results'];qp=case/'fault_run'/bad['quarantine_path']
        checks['bad_quarantined']=bad['status']=='quarantined';checks['bad_bytes_preserved']=qp.is_file() and sha(qp)==sha(case/bad['input_path']);checks['healthy_companion_verified']=good['status']=='verified'
        if kind=='truncated_file':
            control=load(case/'complete_control/summary.json');checks['intact_counterpart_verified']=control['files_verified']==1 and control['record_count']==6
            checks['actual_truncation']=(case/'truncated.xlsx').read_bytes()==(case/'complete.xlsx').read_bytes()[:(case/'complete.xlsx').stat().st_size//2]
    elif kind=='duplicate_replay':
        replay=load(case/'replay/summary.json');checks['idempotent_six']=replay['records_idempotent']==6 and replay['records_inserted']==0
    elif kind=='database_lock':
        lock=load(case/'lock_result.json');checks['actual_lock_duration']=lock['held_ms']>=load(case.parent/'execution_manifest.json')['lock_ms']*.9;checks['actual_busy_retry']=any(e.get('event_type')=='retry' and str(e.get('error_code','')).startswith(('SQLITE_5:','SQLITE_6:')) for e in es)
    elif kind=='transaction_interruption':
        prior=load(case/'interrupted_snapshot.json');check=row_check(prior['rows'],guardexpected);checks['actual_rollback']=check['row_set_equal'] and check['stored_vs_recomputed_hash_equal'];failed=load(case/'fault_run/summary.json');checks['injected_transaction_failure']=failed['files_failed']==1 and 'INJECTED_TRANSACTION_ABORT_AFTER_INSERT' in failed['results'][0]['error_code']
    elif kind=='process_termination':
        expected_at_kill=guardexpected if stage=='hold_before_commit' else expected
        for when in ['pre_kill','post_kill']:
            s=load(case/(when+'_snapshot.json'));v=row_check(s['rows'],expected_at_kill);checks[when+'_state']=v['row_set_equal'] and v['stored_vs_recomputed_hash_equal'] and s['integrity']=='ok'
        ready=load(case/'ready.json');proc=load(case/'terminated/process.json');checks['identified_external_kill']=ready['pid']==proc['pid'] and proc['externally_killed'] and proc['exit_code']!=0
        initial,_=event_list(case/'terminated');checks['no_original_terminal_after_kill']=not any(e.get('event_type')=='terminal' for e in initial)
        wanted='interrupted_uncommitted' if stage=='hold_before_commit' else 'verified_reconciled';checks['correct_reconciliation']=any(a['file_id']==ready['file_id'] and a['status']==wanted for a in audits)
        restart=load(case/'restart/summary.json');checks['restart_insert_vs_idempotency']=restart['records_inserted']==(6 if stage=='hold_before_commit' else 0) and restart['records_idempotent']==(0 if stage=='hold_before_commit' else 6)
    for k,v in checks.items():
        if not v:issues.append(k)
    return {'case_id':case.name,'fault_class':kind,'fault_stage':stage,'trial':reported['trial'],'harness_passed':reported['passed'],'independent_passed':all(checks.values()),'checks':checks,'issues':issues,'row_stats':rowstats,'audit_events_observed':observed,'audit_events_required':required,'audit_event_completeness':observed/required if required else None,'committed_loss':committed_loss,'recover_elapsed_ms':reported.get('recover_elapsed_ms'),'recovery_timing':reported.get('recovery_timing'),'initial_process_terminal_present':reported.get('initial_process_terminal_present')}
def summarize(items):
    grouped={}
    for r in items:grouped.setdefault((r['fault_class'],r['fault_stage']),[]).append(r)
    result=[]
    for (kind,stage),rs in grouped.items():
        times=[r['recover_elapsed_ms'] for r in rs if r['recover_elapsed_ms'] is not None]
        n=len(rs);k=sum(r['independent_passed'] for r in rs)
        known=[r for r in rs if 'row_stats' in r];event_denom=sum(r['audit_events_required'] for r in known)
        result.append({'fault_class':kind,'fault_stage':stage,'trials':n,'harness_passed':sum(r['harness_passed'] for r in rs),'independent_passed':k,'independent_failed':n-k,'unverified_cases':n-len(known),'committed_loss_total_known_cases':sum(r['committed_loss'] for r in known),'duplicate_rows_total_known_cases':sum(r['row_stats']['duplicate_rows'] for r in known),'audit_events_observed':sum(r['audit_events_observed'] for r in known),'audit_events_required_known_cases':event_denom,'audit_completeness_post_reconciliation_known_cases':sum(r['audit_events_observed'] for r in known)/event_denom if event_denom else None,'original_terminal_missing':sum(r.get('initial_process_terminal_present') is False for r in rs),'recover_elapsed_n':len(times),'recover_elapsed_mean_ms':statistics.mean(times) if times else None,'recover_elapsed_sd_ms':statistics.stdev(times) if len(times)>1 else None,'recover_elapsed_min_ms':min(times) if times else None,'recover_elapsed_max_ms':max(times) if times else None,'recovery_timing':rs[0].get('recovery_timing')})
    return result
def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args();base=Path(a.input);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    manifest=load(base/'execution_manifest.json');artifact=load(base/'artifact_verification.json');allowed=set(manifest['artifacts'].values());items=[]
    for path in sorted(base.glob('*/trial_result.json')):
        try:items.append(verify(path.parent,allowed))
        except Exception as e:
            original=load(path);items.append({'case_id':path.parent.name,'fault_class':original['fault_class'],'fault_stage':original['fault_stage'],'trial':original['trial'],'harness_passed':original['passed'],'independent_passed':False,'recover_elapsed_ms':original.get('recover_elapsed_ms'),'recovery_timing':original.get('recovery_timing'),'verification_error':type(e).__name__+': '+str(e)})
    save(out/'independent_trials.json',items)
    groups=summarize(items);csv_output(out/'fault_summary.csv',groups);save(out/'fault_summary.json',groups)
    final={'pilot':manifest['pilot'],'planned_trials':manifest['repeats']*8,'observed_trials':len(items),'independent_passed':sum(r['independent_passed'] for r in items),'independent_failed':sum(not r['independent_passed'] for r in items),'artifacts_unchanged':artifact['unchanged'],'raw_all_trials_sha256':sha(base/'all_trials.json'),'raw_trial_results_sha256':{str(p.relative_to(base)):sha(p) for p in sorted(base.glob('*/trial_result.json'))},'scope':'Prespecified controlled fault observations on one implementation and host. Not a deployment reliability estimate. Completion coverage includes explicit restart reconciliation; missing original terminal events remain counted separately.'}
    save(out/'verification.json',final);print(json.dumps(final,ensure_ascii=False));return 0 if final['independent_failed']==0 and artifact['unchanged'] and len(items)==manifest['repeats']*8 else 1
if __name__=='__main__':raise SystemExit(main())
