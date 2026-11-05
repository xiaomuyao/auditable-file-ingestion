"""External fault injection for a frozen ingestion executable.

Each case owns its inputs, database and subprocess logs. Source files are never
repaired. Process restarts are external replay and are reported separately from
bounded in-process database-lock retry.
"""
import argparse,csv,hashlib,json,os,shutil,sqlite3,subprocess,sys,time,unicodedata,zipfile
from pathlib import Path
from decimal import Decimal

FIELDS=['record_id','dataset','source_category','field','unit','value','source_locator']
TERMINAL={'verified','quarantined','failed','interrupted_uncommitted','verified_reconciled'}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write_json(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
def canonical_hash(row):
    values=[unicodedata.normalize('NFC',str(row[k]).strip()) for k in FIELDS]
    values[5]=format(Decimal(values[5]),'f').rstrip('0').rstrip('.') if '.' in format(Decimal(values[5]),'f') else format(Decimal(values[5]),'f')
    return hashlib.sha256(json.dumps(values,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()
def records(prefix,n=6):return [dict(zip(FIELDS,[f'{prefix}-r{i+1:03d}','fault_fixture','controlled_injection','force','N','123.456',f'fixture:row{i+2}'])) for i in range(n)]
def csv_file(path,rows,fields=FIELDS):
    with Path(path).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def xlsx_file(path,rows):
    from xml.sax.saxutils import escape
    def col(i):return chr(65+i)
    matrix=[FIELDS]+[[r[k] for k in FIELDS] for r in rows]
    rs=[]
    for i,row in enumerate(matrix,1):rs.append('<row r="%d">'%i+''.join('<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>'%(col(j),i,escape(str(s))) for j,s in enumerate(row))+'</row>')
    parts={'[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
    '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
    'xl/workbook.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Records" sheetId="1" r:id="rId1"/></sheets></workbook>',
    'xl/_rels/workbook.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
    'xl/worksheets/sheet1.xml':'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(rs)+'</sheetData></worksheet>'}
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for k,v in parts.items():z.writestr(k,v)
def manifest(path,files):write_json(path,{'files':[{'path':str(Path(f).relative_to(Path(path).parent)),'decimal_locale':'invariant','encoding':'utf-8','delimiter':','} for f in files]})

def snapshot(db):
    con=sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True,timeout=10);con.row_factory=sqlite3.Row
    try:
        con.execute('PRAGMA query_only=ON')
        rows=[dict(r) for r in con.execute('SELECT * FROM records ORDER BY record_id')]
        audits=[dict(r) for r in con.execute('SELECT * FROM file_audit ORDER BY started_utc,file_id')]
        sources=[dict(r) for r in con.execute('SELECT * FROM record_sources ORDER BY file_id,record_id')]
        integrity=con.execute('PRAGMA integrity_check').fetchone()[0]
        foreign_key_errors=[list(r) for r in con.execute('PRAGMA foreign_key_check')]
        return {'rows':rows,'audits':audits,'sources':sources,'integrity':integrity,'foreign_key_errors':foreign_key_errors}
    finally:con.close()
def expected(rows):return {r['record_id']:canonical_hash(r) for r in rows}
def verify_rows(s,truth):
    observed={r['record_id']:r['canonical_hash'] for r in s['rows']}
    recalculated={r['record_id']:canonical_hash(r) for r in s['rows']}
    return {'expected_records':len(truth),'actual_records':len(s['rows']),'duplicate_rows':len(s['rows'])-len(observed),'missing_records':sum(observed.get(k)!=v for k,v in truth.items()),'unexpected_records':len(set(observed)-set(truth)),'hash_mismatches':sum(recalculated[k]!=observed[k] for k in observed),'row_set_equal':observed==truth and observed==recalculated,'integrity_ok':s['integrity']=='ok'}
def events(directory):
    result=[];malformed=[]
    for p in Path(directory).rglob('events.jsonl'):
        for i,line in enumerate(p.read_text(encoding='utf-8').splitlines(),1):
            try:result.append(dict(json.loads(line),event_file=str(p.relative_to(directory)),line=i))
            except Exception:malformed.append({'file':str(p.relative_to(directory)),'line':i,'text':line})
    return result,malformed
def audit_checks(s,ev,mode,stage):
    checks={'all_audits_terminal':all(a['status'] in TERMINAL and a['completed_utc'] for a in s['audits']),
    'audit_identity_metadata':all(a['input_sha256'] and a['plugin_name'] and a['plugin_version'] and a['plugin_sha256'] for a in s['audits']),
    'intent_for_every_audit':all(any(e.get('event_type')=='intent' and e.get('file_id')==a['file_id'] for e in ev) for a in s['audits']),
    'source_rows_reference_audit':all(any(a['file_id']==r['file_id'] for a in s['audits']) for r in s['sources'])}
    def completion(a):
        return any((e.get('event_type')=='terminal' and e.get('result',{}).get('file_id')==a['file_id'] and e['result'].get('status')==a['status']) or (e.get('event_type')=='reconcile' and e.get('file_id')==a['file_id'] and e.get('status')==a['status']) for e in ev)
    checks['terminal_or_reconciliation_for_every_audit']=all(completion(a) for a in s['audits'])
    checks['foreign_keys_consistent']=not s['foreign_key_errors']
    if mode=='process_termination':
        wanted='interrupted_uncommitted' if stage=='hold_before_commit' else 'verified_reconciled'
        checks['restart_reconciliation_observed']=any(e.get('event_type')=='reconcile' and e.get('status')==wanted for e in ev)
        checks['prior_audit_reconciled']=any(a['status']==wanted for a in s['audits'])
    checks['verified_source_hashes_match']=all(next((r['canonical_hash'] for r in s['rows'] if r['record_id']==src['record_id']),None)==src['canonical_hash'] for src in s['sources'])
    return checks

def audit_event_coverage(s,ev):
    """A durable intent and terminal-or-reconciliation event per file audit.

    A reconciliation event substitutes for the completion event of a terminated
    process. Missing original terminal events are separately reported, never
    imputed as having existed in that process.
    """
    covered=0
    for a in s['audits']:
        covered+=any(e.get('event_type')=='intent' and e.get('file_id')==a['file_id'] for e in ev)
        covered+=any((e.get('event_type')=='terminal' and e.get('result',{}).get('file_id')==a['file_id'] and e['result'].get('status')==a['status']) or (e.get('event_type')=='reconcile' and e.get('file_id')==a['file_id'] and e.get('status')==a['status']) for e in ev)
    return covered,2*len(s['audits'])

class Harness:
    def __init__(self,a):self.a=a;self.host=Path(a.host).resolve();self.plugins=Path(a.plugins).resolve();self.out=Path(a.output).resolve();self.out.mkdir(parents=True,exist_ok=True)
    def cmd(self,man,db,out,plugins=None,fault=None,signal=None):
        cmd=[str(self.host),'ingest','--input',str(man),'--db',str(db),'--output',str(out),'--plugins',str(plugins or self.plugins),'--concurrency','1','--python',sys.executable]
        if fault:cmd+=['--fault',fault]
        if signal:cmd+=['--signal',str(signal)]
        return cmd
    def run(self,cmd,where,wait=True):
        where=Path(where);where.mkdir(parents=True,exist_ok=True)
        sf=(where/'stdout.log').open('wb');ef=(where/'stderr.log').open('wb')
        started=time.perf_counter();p=subprocess.Popen(cmd,stdout=sf,stderr=ef,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        meta={'pid':p.pid,'command':cmd,'started_monotonic_s':started}
        write_json(where/'process.json',meta)
        if not wait:return p,sf,ef,started,meta
        try:rc=p.wait(timeout=30)
        except subprocess.TimeoutExpired:p.kill();rc=p.wait(timeout=10);meta['timeout']=True
        sf.close();ef.close();meta.update(exit_code=rc,elapsed_ms=(time.perf_counter()-started)*1000);write_json(where/'process.json',meta)
        return meta
    def seed(self,case,db):
        guard=records('guard-'+case.name,1);f=case/'guard.csv';csv_file(f,guard);man=case/'guard_manifest.json';manifest(man,[f]);run=self.run(self.cmd(man,db,case/'seed'),case/'seed')
        if run['exit_code']!=0:raise RuntimeError('Guard ingestion failed')
        snap=snapshot(db);v=verify_rows(snap,expected(guard));write_json(case/'seed_snapshot.json',snap)
        if not v['row_set_equal']:raise RuntimeError('Guard verification failed: '+str(v))
        return guard
    def case(self,kind,index,stage=''):
        name=f'{kind}-{stage+"-" if stage else ""}{index:02d}';case=self.out/name
        if case.exists():raise FileExistsError('Do not overwrite prior trial: '+str(case))
        case.mkdir();db=case/'records.sqlite';result={'case_id':name,'fault_class':kind,'fault_stage':stage,'trial':index,'source_category':'controlled_injection','planned':True,'passed':False}
        began=time.perf_counter();subruns=[];guard=[];good=[];committed_truth={};helper=None
        try:
            guard=self.seed(case,db);committed_truth=expected(guard);good=records(name);goodfile=case/'input.csv';csv_file(goodfile,good);man=case/'manifest.json';fault=None;plug=self.plugins
            if kind in ['truncated_file','missing_fields','plugin_exception']:
                if kind=='truncated_file':
                    original=case/'complete.xlsx';xlsx_file(original,good);bad=case/'truncated.xlsx';data=original.read_bytes();bad.write_bytes(data[:len(data)//2]);result.update(original_sha256=sha(original),truncated_bytes=len(data)//2,original_bytes=len(data))
                    control_man=case/'complete_manifest.json';manifest(control_man,[original]);control=self.run(self.cmd(control_man,case/'control.sqlite',case/'complete_control'),case/'complete_control')
                    result['intact_counterpart_control']=verify_rows(snapshot(case/'control.sqlite'),expected(good));result['intact_counterpart_exit_code']=control['exit_code']
                elif kind=='missing_fields':bad=case/'missing.csv';csv_file(bad,good,[f for f in FIELDS if f!='value'])
                else:
                    bad=case/'exception.throw';bad.write_bytes(goodfile.read_bytes());plug=case/'test_plugins';shutil.copytree(self.plugins,plug);shutil.copy2(self.a.throwing_plugin,plug/Path(self.a.throwing_plugin).name)
                healthy=records(name+'-healthy');healthyfile=case/'healthy.csv';csv_file(healthyfile,healthy);manifest(man,[bad,healthyfile]);before=sha(bad)
                r=self.run(self.cmd(man,db,case/'fault_run',plug),case/'fault_run');subruns.append(r)
                summary=json.loads((case/'fault_run/summary.json').read_text(encoding='utf-8'))
                rejected=summary['results'][0];continuation=summary['results'][1]
                quarantine=Path(rejected.get('quarantine_path',''))
                if not quarantine.is_absolute():quarantine=case/'fault_run'/quarantine
                result.update(source_sha256=before,source_unchanged=sha(bad)==before,failure_detected=rejected['status'] in ['failed','quarantined'],rejection_status=rejected['status'],quarantine_exists=quarantine.is_file(),quarantine_hash_equal=quarantine.is_file() and sha(quarantine)==before,healthy_continuation_verified=continuation['status']=='verified',outcome='permanent_input_isolated')
                good=healthy;truth={**expected(guard),**expected(healthy)};result['recovery_kind']='not_applicable_permanent_rejection'
            elif kind=='duplicate_replay':
                manifest(man,[goodfile]);first=self.run(self.cmd(man,db,case/'first'),case/'first');subruns.append(first)
                committed_truth={**expected(guard),**expected(good)};result['first_committed_check']=verify_rows(snapshot(db),committed_truth)
                second=self.run(self.cmd(man,db,case/'replay'),case/'replay');subruns.append(second)
                summary=json.loads((case/'replay/summary.json').read_text(encoding='utf-8'))
                result.update(failure_detected=None,replay_recognized=summary['records_idempotent']==len(good),idempotent_rows=summary['records_idempotent'],replay_inserted_rows=summary['records_inserted'],source_unchanged=True,outcome='exact_replay_idempotent',recovery_kind='idempotent_replay',recover_elapsed_ms=second['elapsed_ms'],recovery_timing='replay_process_start_to_verified_exit')
                truth=committed_truth
            elif kind=='database_lock':
                manifest(man,[goodfile]);ready=case/'lock_ready.json';released=case/'lock_result.json'
                helper=self.run([sys.executable,str(Path(__file__).with_name('lock_helper.py')),'--db',str(db),'--ready',str(ready),'--release-ms',str(self.a.lock_ms),'--result',str(released)],case/'lock_helper',False)
                self.wait_ready(ready,helper[0],10);before=sha(goodfile);r=self.run(self.cmd(man,db,case/'fault_run'),case/'fault_run');subruns.append(r)
                hp,sf,ef,hs,hm=helper;hp.wait(timeout=10);sf.close();ef.close();helper=None
                lock=json.loads(released.read_text(encoding='utf-8'));summary=json.loads((case/'fault_run/summary.json').read_text(encoding='utf-8'));ev,_=events(case)
                result.update(failure_detected=any(e.get('event_type')=='retry' for e in ev),retry_events=sum(e.get('event_type')=='retry' for e in ev),record_retries=sum(x['retries'] for x in summary['results']),source_unchanged=sha(goodfile)==before,lock_observation=lock,outcome='transient_lock_automatic_retry',recovery_kind='bounded_host_retry',recover_elapsed_ms=r['elapsed_ms'],recovery_timing='host_process_start_to_verified_exit_including_startup_and_retry')
                truth={**expected(guard),**expected(good)}
            elif kind=='transaction_interruption':
                manifest(man,[goodfile]);before=sha(goodfile);r=self.run(self.cmd(man,db,case/'fault_run',fault='transaction_abort'),case/'fault_run');subruns.append(r)
                s=snapshot(db);write_json(case/'interrupted_snapshot.json',s);result['interrupted_snapshot']=verify_rows(s,expected(guard));result['failure_detected']=r['exit_code']!=0
                r=self.run(self.cmd(man,db,case/'restart'),case/'restart');subruns.append(r)
                result.update(source_unchanged=sha(goodfile)==before,outcome='rolled_back_then_restart_replay',recovery_kind='external_restart_replay',recover_elapsed_ms=r['elapsed_ms'],recovery_timing='restart_process_start_to_verified_exit');truth={**expected(guard),**expected(good)}
            elif kind=='process_termination':
                manifest(man,[goodfile]);before=sha(goodfile);ready=case/'ready.json';proc,sf,ef,st,meta=self.run(self.cmd(man,db,case/'terminated',fault=stage,signal=ready),case/'terminated',False)
                signal=self.wait_ready(ready,proc,15);assert signal['pid']==proc.pid
                before_kill=snapshot(db);write_json(case/'pre_kill_snapshot.json',before_kill);result['ready_signal']=signal;result['pre_kill_snapshot']=verify_rows(before_kill,expected(guard) if stage=='hold_before_commit' else {**expected(guard),**expected(good)})
                kill_started=time.perf_counter();proc.kill();rc=proc.wait(timeout=10);sf.close();ef.close();meta.update(exit_code=rc,externally_killed=True,elapsed_ms=(time.perf_counter()-st)*1000);write_json(case/'terminated/process.json',meta);subruns.append(meta)
                committed_truth=expected(guard) if stage=='hold_before_commit' else {**expected(guard),**expected(good)}
                after_kill=snapshot(db);write_json(case/'post_kill_snapshot.json',after_kill);result['post_kill_snapshot']=verify_rows(after_kill,committed_truth);result['failure_detected']=rc!=0
                restart=self.run(self.cmd(man,db,case/'restart'),case/'restart');subruns.append(restart)
                recovered_at=time.perf_counter();initial,_=events(case/'terminated');result.update(initial_process_terminal_present=any(e.get('event_type')=='terminal' for e in initial),source_unchanged=sha(goodfile)==before,outcome='hard_kill_then_restart_replay',recovery_kind='external_restart_reconciliation',recover_elapsed_ms=(recovered_at-kill_started)*1000,restart_process_ms=restart['elapsed_ms'],recovery_timing='external_kill_request_to_restart_verified_exit_including_post_kill_readonly_snapshot')
                truth={**expected(guard),**expected(good)}
            else:raise ValueError(kind)
            snap=snapshot(db);v=verify_rows(snap,truth);result.update(v);result['committed_loss']=sum(next((r['canonical_hash'] for r in snap['rows'] if r['record_id']==k),None)!=h for k,h in committed_truth.items())
            ev,malformed=events(case);ac=audit_checks(snap,ev,kind,stage);covered,required=audit_event_coverage(snap,ev);result.update(audit_checks=ac,audit_checks_required=len(ac),audit_checks_passed=sum(ac.values()),audit_events_observed=covered,audit_events_required=required,audit_event_completeness=covered/required if required else None,malformed_audit_lines=malformed)
            checks=[v['row_set_equal'],v['integrity_ok'],result['committed_loss']==0,not malformed,all(ac.values()),result.get('source_unchanged',False)]
            if kind in ['truncated_file','missing_fields','plugin_exception']:checks.extend([result['failure_detected'],result['quarantine_hash_equal'],result['healthy_continuation_verified']])
            if kind=='truncated_file':checks.extend([result['intact_counterpart_control']['row_set_equal'],result['intact_counterpart_exit_code']==0])
            if kind=='duplicate_replay':checks.extend([result['first_committed_check']['row_set_equal'],result['idempotent_rows']==len(good),result['replay_inserted_rows']==0])
            if kind=='database_lock':checks.extend([result['failure_detected'],result['lock_observation']['held_ms']>=self.a.lock_ms*.9])
            if kind=='transaction_interruption':checks.extend([result['failure_detected'],result['interrupted_snapshot']['row_set_equal']])
            if kind=='process_termination':checks.extend([result['failure_detected'],result['pre_kill_snapshot']['row_set_equal'],result['post_kill_snapshot']['row_set_equal'],not result['initial_process_terminal_present']])
            result['passed']=all(checks);write_json(case/'final_snapshot.json',snap);write_json(case/'expected_records.json',truth)
        except Exception as e:result['harness_error']=type(e).__name__+':'+str(e)
        finally:
            if helper:
                hp,sf,ef,_,_=helper
                if hp.poll() is None:hp.kill();hp.wait(timeout=10)
                sf.close();ef.close()
            result.update(elapsed_ms=(time.perf_counter()-began)*1000,subprocesses=subruns)
            result.setdefault('recover_elapsed_ms',None)
            write_json(case/'trial_result.json',result)
        return result
    @staticmethod
    def wait_ready(path,proc,seconds):
        end=time.perf_counter()+seconds
        while time.perf_counter()<end:
            if Path(path).exists():
                try:return json.loads(Path(path).read_text(encoding='utf-8'))
                except json.JSONDecodeError:pass
            if proc.poll() is not None:raise RuntimeError('Process exited before ready marker')
            time.sleep(.005)
        proc.kill();proc.wait(timeout=10);raise TimeoutError('Ready marker not observed')

def main():
    p=argparse.ArgumentParser();p.add_argument('--host',required=True);p.add_argument('--plugins',required=True);p.add_argument('--throwing-plugin',required=True);p.add_argument('--output',required=True);p.add_argument('--freeze-manifest');p.add_argument('--repeats',type=int,default=10);p.add_argument('--lock-ms',type=int,default=300);p.add_argument('--pilot',action='store_true');a=p.parse_args()
    if not a.pilot and not a.freeze_manifest:p.error('Formal runs require a declared freeze manifest')
    artifacts=[Path(a.host),*Path(a.plugins).glob('*.dll'),Path(a.throwing_plugin)]
    # Shared host dependencies are relevant executable artifacts as well.
    artifacts+=list(Path(a.host).parent.glob('*.dll'))
    frozen={str(x.resolve()):sha(x) for x in artifacts};declared={};freeze_match=None
    if a.freeze_manifest:
        fp=Path(a.freeze_manifest).resolve();document=json.loads(fp.read_text(encoding='utf-8-sig'))
        declared={str((fp.parent/item['path']).resolve()):item['sha256'] for item in document['files']}
        freeze_match=all(Path(path).is_file() and sha(path)==value for path,value in declared.items()) and all(declared.get(path)==value for path,value in frozen.items())
        if not freeze_match:raise RuntimeError('Declared final freeze does not match all declared files and executed artifacts')
    h=Harness(a)
    write_json(h.out/'execution_manifest.json',{'pilot':a.pilot,'freeze_manifest_sha256':sha(a.freeze_manifest) if a.freeze_manifest else None,'freeze_matched_before':freeze_match,'declared_freeze_files':declared,'artifacts':frozen,'repeats':a.repeats,'lock_ms':a.lock_ms,'python':sys.version,'protocol_version':2,'source_repairs':False,'abnormal_termination_subconditions':['hold_before_commit','hold_after_commit']})
    results=[]
    for kind in ['truncated_file','missing_fields','plugin_exception','duplicate_replay','database_lock','transaction_interruption','process_termination']:
        for stage in (['hold_before_commit','hold_after_commit'] if kind=='process_termination' else ['']):
            for i in range(1,a.repeats+1):
                r=h.case(kind,i,stage);results.append(r);write_json(h.out/'all_trials.json',results);print(r['case_id'],r['passed'],r.get('harness_error',''),flush=True)
    after={str(x.resolve()):sha(x) for x in artifacts};declared_after={path:sha(path) if Path(path).is_file() else None for path in declared};unchanged=after==frozen and (not declared or declared_after==declared)
    write_json(h.out/'artifact_verification.json',{'unchanged':unchanged,'freeze_matched_after':declared_after==declared if declared else None,'declared_after':declared_after,'before':frozen,'after':after})
    cols=['case_id','fault_class','fault_stage','trial','passed','outcome','failure_detected','expected_records','actual_records','duplicate_rows','missing_records','unexpected_records','hash_mismatches','committed_loss','audit_events_observed','audit_events_required','audit_event_completeness','initial_process_terminal_present','retry_events','source_unchanged','recovery_kind','recovery_timing','recover_elapsed_ms','restart_process_ms','elapsed_ms','harness_error']
    with (h.out/'fault_trials.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(results)
    summary={'planned_trials':a.repeats*8,'observed_trials':len(results),'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),'artifacts_unchanged':unchanged,'pilot':a.pilot}
    write_json(h.out/'summary.json',summary);print(json.dumps(summary),flush=True)
    return 0 if all(r['passed'] for r in results) and unchanged else 1

if __name__=='__main__':raise SystemExit(main())
