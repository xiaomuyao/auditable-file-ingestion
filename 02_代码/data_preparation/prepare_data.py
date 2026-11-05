"""Pre-registered scalar selection and deterministic controlled import fixtures.

No adapter code is imported or changed. Holdout download is gated by a final
freeze manifest and is performed once, after the six adapters/PDF bridge freeze.
"""
from pathlib import Path
from decimal import Decimal,InvalidOperation
import csv,json,hashlib,datetime,argparse,shutil,subprocess,sqlite3,zipfile,urllib.request,io,os,xml.etree.ElementTree as ET
from docx import Document
from docx.shared import Pt
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import landscape,A4

FIELDS=['record_id','dataset','source_category','field','unit','value','source_locator']
SOURCES={
 'hydraulic':{'title':'Condition monitoring of hydraulic systems','uci_id':447,'doi':'10.24432/C5CW21','category':'public_real','page':'https://archive.ics.uci.edu/dataset/447/condition+monitoring+of+hydraulic+systems','member':'TS1.txt','selection':'first 120 physical rows whose first tab-separated scalar is finite Decimal; preserve original scalar text','unit':'degC','field':'TS1'},
 'ai4i':{'title':'AI4I 2020 Predictive Maintenance Dataset','uci_id':601,'doi':'10.24432/C5HS5C','category':'public_synthetic','page':'https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset','member':'ai4i2020.csv','selection':'first 120 CSV data rows whose Torque [Nm] cell is finite Decimal; preserve original scalar text','unit':'Nm','field':'Torque'},
 'holdout':{'title':'Beijing PM2.5','uci_id':381,'doi':'10.24432/C5JS49','category':'public_real','page':'https://archive.ics.uci.edu/dataset/381/beijing+pm2+5+data','member':'PRSA_data_2010.1.1-2014.12.31.csv','download':'https://archive.ics.uci.edu/static/public/381/beijing+pm2+5+data.zip','selection':'first 120 CSV data rows with finite numeric pm2.5, skipping NA; preserve original scalar text; no selection by adapter outcome','unit':'ug/m3','field':'pm2.5'}
}
LICENSE='https://creativecommons.org/licenses/by/4.0/'
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def csvwrite(p,rows,fields=None,encoding='utf-8',delimiter=','):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding=encoding,newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields or list(rows[0]),delimiter=delimiter,extrasaction='ignore');w.writeheader();w.writerows(rows)
def jsonwrite(p,obj):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def finite(v):
 try:return Decimal(v).is_finite()
 except (InvalidOperation,ValueError,TypeError):return False
def canonical_decimal(v):
 number=Decimal(v)
 if number==0:return '0'
 text=format(number,'f')
 return text.rstrip('0').rstrip('.') if '.' in text else text
def download(url,path):
 if path.exists():raise RuntimeError('Refusing to overwrite downloaded evidence '+str(path))
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Academic-source-audit/1.0'}),timeout=60) as r:data=r.read()
 path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
 return {'url':url,'path':path.name,'bytes':len(data),'sha256':sha(path),'retrieved_at_utc':utc()}
def register(root):
 protocol={'registered_at_utc':utc(),'schema':FIELDS,'n_per_source':120,'base_sources':['hydraulic','ai4i'],'holdout':'holdout','sources':SOURCES,'license':'CC BY 4.0','license_url':LICENSE,'source_numeric_text':'Original selected scalar strings are retained in canonical truth. Explicit transport-locale variants are derived and expected to normalize to the same decimal value.','holdout_rules':['No third-source data bytes may be downloaded or read before final six-adapter plus Host plus PDF-bridge freeze.','Read only official metadata before final freeze.','First holdout adapter run timestamp/run ID must be recorded, and no second adaptive run is permitted.','Observed failures remain results; no post-holdout parser correction.'],'duplicate_contract':{'within_file_same':'reject entire file','within_file_conflict':'reject entire file','cross_file_same':'canonical identity idempotent, no extra insertion','cross_file_conflict':'reject conflicting file atomically; earlier committed file retained'}}
 p=root/'protocol_pre_registration.json'
 if p.exists():
  amendment=root/'protocol_amendments.json'
  if not amendment.exists():jsonwrite(amendment,{'amended_at_utc':utc(),'predecessor_protocol_sha256':sha(p),'before_holdout_download':True,'reason':'Canonical contract clarified before adapter freeze: Decimal.ToString(G29,InvariantCulture) semantics.','canonical_decimal':'Finite Decimal, fixed notation, remove insignificant fractional trailing zeroes and decimal point, normalize signed zero to 0; selected original string retained in lineage.original_value.','selection_rules_unchanged':True})
  return json.loads(p.read_text(encoding='utf-8'))
 jsonwrite(p,protocol);jsonwrite(root/'holdout'/'holdout_untouched.json',{'status':'metadata_only_untouched','registered_at_utc':protocol['registered_at_utc'],'data_downloaded':False,'data_read':False,'protocol_sha256':sha(p),'holdout_source':SOURCES['holdout'],'release_gate':'Final freeze manifest covering Host, all six adapters and Python PDF bridge'})
 return protocol
def metadata(root,legacy):
 directory=root/'source_metadata';directory.mkdir(parents=True,exist_ok=True)
 records=[dict(v,license='CC BY 4.0',license_url=LICENSE,official_metadata_verified_on='2026-10-21',verification_method='Official UCI landing-page metadata; data download excluded from this metadata check') for v in SOURCES.values()]
 jsonwrite(directory/'metadata_review.json',{'sources':records,'license_terms_verified':'CC BY 4.0 permits redistribution and adaptation with attribution, license link and changes indicated.','primary_license_url':LICENSE})
 if legacy:
  for name in ['hydraulic_page.html','ai4i_page.html','CC_BY_4.0.html','download_manifest.json']:
   src=legacy/name
   if src.exists():shutil.copyfile(src,directory/('prior_'+name))
def select_base(legacy,rawdir):
 rawdir.mkdir(parents=True,exist_ok=True);source_records=[];rows=[];lineage=[]
 for key,prefix in [('hydraulic','H'),('ai4i','A')]:
  info=SOURCES[key];src=legacy/info['member'];target=rawdir/info['member']
  if target.exists():assert sha(src)==sha(target)
  else:shutil.copyfile(src,target)
  before=sha(src);source_records.append({'source_key':key,'source_category':info['category'],'path':info['member'],'sha256':before,'bytes':src.stat().st_size,'source_page':info['page'],'doi':info['doi'],'license':'CC BY 4.0','license_url':LICENSE,'copy_matches_legacy':before==sha(target)})
  if key=='hydraulic':items=[(i,line.split('\t')[0],'1') for i,line in enumerate(src.read_text(encoding='utf-8-sig').splitlines(),1)]
  else:
   with src.open(encoding='utf-8-sig',newline='') as f:items=[(i,r['Torque [Nm]'],'Torque [Nm]') for i,r in enumerate(csv.DictReader(f),2)]
  valid=[x for x in items if finite(x[1])][:120];assert len(valid)==120
  for index,(rownum,value,col) in enumerate(valid,1):
   rid=f'{prefix}{index:04d}';locator=f'https://archive.ics.uci.edu/dataset/{info["uci_id"]}#{info["member"]}:row={rownum}:col={col}'
   normalized=canonical_decimal(value);rows.append(dict(zip(FIELDS,[rid,'Hydraulic' if key=='hydraulic' else 'AI4I',info['category'],info['field'],info['unit'],normalized,locator])));lineage.append({'record_id':rid,'source_key':key,'source_member':info['member'],'physical_row':rownum,'source_column':col,'original_value':value,'canonical_value':normalized,'source_sha256':before})
  assert before==sha(src)
 return rows,lineage,source_records
def pdfwrite(p,headers,rows):
 p.parent.mkdir(parents=True,exist_ok=True);c=canvas.Canvas(str(p),pagesize=landscape(A4),invariant=1);c.setAuthor('');c.setCreator('');c.setTitle('Controlled report import fixture')
 width,height=landscape(A4);y=height-25;c.setFont('Courier',7)
 for line in ['|'.join(headers)]+['|'.join(str(r.get(k,'')) for k in headers) for r in rows]:
  if c.stringWidth(line,'Courier',7)>width-40:raise ValueError('Report fixture line would wrap')
  if y<20:c.showPage();c.setFont('Courier',7);y=height-25
  c.drawString(20,y,line);y-=10
 c.save()
def write_fixture(p,headers,rows,fmt,xlsx_jobs,encoding='utf-8',delimiter=','):
 p.parent.mkdir(parents=True,exist_ok=True)
 if fmt=='csv':csvwrite(p,rows,headers,encoding,delimiter)
 elif fmt=='sqlite':
  if p.exists():p.unlink()
  with sqlite3.connect(p) as con:
   con.execute('CREATE TABLE canonical_records ('+','.join('"'+k+'" TEXT' for k in headers)+')')
   con.executemany('INSERT INTO canonical_records VALUES ('+','.join('?' for _ in headers)+')',[[r.get(k,'') for k in headers] for r in rows])
 elif fmt=='docx':
  d=Document();d.core_properties.author='';d.core_properties.last_modified_by='';d.styles['Normal'].font.size=Pt(7)
  d.core_properties.created=datetime.datetime(2000,1,1,tzinfo=datetime.timezone.utc);d.core_properties.modified=d.core_properties.created
  t=d.add_table(rows=1,cols=len(headers));t.style='Table Grid'
  for cell,k in zip(t.rows[0].cells,headers):cell.text=k
  for r in rows:
   for cell,k in zip(t.add_row().cells,headers):cell.text=str(r.get(k,''))
  d.save(p)
  with zipfile.ZipFile(p) as z:parts=[(i.filename,z.read(i.filename)) for i in z.infolist()]
  with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED) as z:
   for name,content in parts:zipwrite(z,name,content)
 elif fmt=='pdf':pdfwrite(p,headers,rows)
 elif fmt=='xlsx':xlsx_jobs.append({'path':str(p.resolve()),'headers':headers,'rows':[[str(r.get(k,'')) for k in headers] for r in rows]})
 elif fmt=='json':jsonwrite(p,[{k:r.get(k,'') for k in headers} for r in rows])
 else:raise ValueError(fmt)
def zipwrite(z,name,data):
 info=zipfile.ZipInfo(name,date_time=(2000,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,data)
def ooxml_write(job):
 """Publicly rebuildable ISO/IEC 29500 subset: one sheet, inline text cells."""
 ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main';ET.register_namespace('',ns)
 root=ET.Element('{'+ns+'}worksheet');sheet=ET.SubElement(root,'{'+ns+'}sheetData')
 for ri,values in enumerate([job['headers']]+job['rows'],1):
  row=ET.SubElement(sheet,'{'+ns+'}row',r=str(ri))
  for ci,value in enumerate(values,1):
   col='';n=ci
   while n:n,m=divmod(n-1,26);col=chr(65+m)+col
   cell=ET.SubElement(row,'{'+ns+'}c',r=f'{col}{ri}',t='inlineStr');inline=ET.SubElement(cell,'{'+ns+'}is');text=ET.SubElement(inline,'{'+ns+'}t');text.text=str(value)
   if str(value)!=str(value).strip():text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
 p=Path(job['path']);p.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED) as z:
  zipwrite(z,'[Content_Types].xml','<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
  zipwrite(z,'_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
  zipwrite(z,'xl/workbook.xml','<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Canonical" sheetId="1" r:id="rId1"/></sheets></workbook>')
  zipwrite(z,'xl/_rels/workbook.xml.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
  zipwrite(z,'xl/worksheets/sheet1.xml',ET.tostring(root,encoding='utf-8',xml_declaration=True))
def generate(root,partition,truth,node,builder,toolwork,artifact_modules,include_json=False,xlsx_writer='standard-ooxml'):
 destination=root/partition;destination.mkdir(parents=True,exist_ok=True);jobs=[];manifest=[];plans=[]
 formats=['csv','xlsx','sqlite','docx','pdf']+(['json'] if include_json else [])
 def case(name,headers,rr,expected,locale='invariant',encoding='utf-8',which=None):
  files=[]
  for fmt in which or formats:
   p=destination/('fixtures' if name=='normal' else 'variants/'+name)/('records.'+fmt)
   write_fixture(p,headers,rr,fmt,jobs,encoding=encoding)
   options={'path':p.relative_to(destination).as_posix() if name=='normal' else p.name,'decimal_locale':locale,'encoding':encoding,'delimiter':','}
   files.append(options);plans.append((p,{'partition':partition,'case':name,'format':fmt,'relative_path':p.relative_to(root).as_posix(),'encoding':encoding if fmt=='csv' else 'format_defined','decimal_locale':locale,'input_rows':len(rr),'required_fields_present':all(k in headers for k in FIELDS),'expected_outcome':expected,'expected_inserted_rows':len(truth) if expected=='accept' else 0,'truth_path':(destination/'canonical_ground_truth.csv').relative_to(root).as_posix(),'transformation':'identity' if name=='normal' else name}))
  mpath=destination/('manifest.json' if name=='normal' else 'variants/'+name+'/manifest.json');jsonwrite(mpath,{'files':files,'expected_outcome':expected,'case':name,'schema':FIELDS,'expected_final_unique_rows':len(truth) if expected=='accept' else 0,'case_execution':'Run each manifest against a fresh store. Within each manifest files execute in listed order.'})
 case('normal',FIELDS,truth,'accept')
 case('columns_reordered',list(reversed(FIELDS)),truth,'accept')
 extra=[dict(r,ignored_note='controlled-extra-column') for r in truth];case('extra_column',FIELDS+['ignored_note'],extra,'accept')
 case('missing_required_value',[k for k in FIELDS if k!='value'],truth,'reject_file')
 case('duplicate_id_same_value',FIELDS,truth+[dict(truth[0])],'reject_file')
 changed=dict(truth[0]);changed['value']=str(Decimal(changed['value'])+Decimal(1));case('duplicate_id_conflict',FIELDS,truth+[changed],'reject_file')
 localized=[dict(r,value=r['value'].replace('.',',')) for r in truth];case('explicit_de-DE',FIELDS,localized,'accept','de-DE')
 case('utf8_bom',FIELDS,truth,'accept',encoding='utf-8-sig',which=['csv'])
 case('utf16',FIELDS,truth,'accept',encoding='utf-16',which=['csv'])
 case('utf16_wrong_encoding',FIELDS,truth,'reject_file',encoding='utf-16',which=['csv'])
 wrong=destination/'variants'/'utf16_wrong_encoding'/'manifest.json';obj=json.loads(wrong.read_text(encoding='utf-8'));obj['files'][0]['encoding']='utf-8';jsonwrite(wrong,obj)
 # Cross-file contract cases are ordered import manifests, not duplicate rows within one file.
 for cname,second,expected2 in [('cross_file_idempotent',[dict(r) for r in truth[:10]],'idempotent_no_new_rows'),('cross_file_conflict',[changed]+[dict(r) for r in truth[1:10]],'reject_file')]:
  directory=destination/'variants'/cname;p=directory/'first.csv';q=directory/'second.xlsx';write_fixture(p,FIELDS,truth,'csv',jobs);write_fixture(q,FIELDS,second,'xlsx',jobs)
  jsonwrite(directory/'manifest.json',{'files':[{'path':p.name,'decimal_locale':'invariant','encoding':'utf-8','delimiter':','},{'path':q.name,'decimal_locale':'invariant','encoding':'format_defined','delimiter':','}],'case':cname,'expected_file_outcomes':['accept',expected2],'expected_final_unique_rows':len(truth),'expected_second_inserted_rows':0})
  for fp,fmt,rr,outcome in [(p,'csv',truth,'accept'),(q,'xlsx',second,expected2)]:plans.append((fp,{'partition':partition,'case':cname,'format':fmt,'relative_path':fp.relative_to(root).as_posix(),'encoding':'utf-8' if fmt=='csv' else 'format_defined','decimal_locale':'invariant','input_rows':len(rr),'required_fields_present':True,'expected_outcome':outcome,'expected_inserted_rows':len(truth) if fp==p else 0,'truth_path':(destination/'canonical_ground_truth.csv').relative_to(root).as_posix(),'transformation':cname}))
 # XLSX uses the supported Artifact Tool writer. No openpyxl authoring.
 if xlsx_writer=='artifact':
  toolwork.mkdir(parents=True,exist_ok=True);shutil.copyfile(builder,toolwork/'build_xlsx.mjs');junction=toolwork/'node_modules'
  if not junction.exists():
   command="New-Item -ItemType Junction -Path $args[0] -Target $args[1] | Out-Null"
   subprocess.run(['powershell','-NoProfile','-Command',command,str(junction.resolve()),str(artifact_modules.resolve())],check=True)
  spec=toolwork/(partition+'_xlsx_jobs.json');jsonwrite(spec,{'jobs':jobs,'preview':str((toolwork/(partition+'_xlsx_preview.png')).resolve())})
  subprocess.run([str(node),str(toolwork/'build_xlsx.mjs'),str(spec)],check=True)
 else:
  for job in jobs:ooxml_write(job)
 for fmt in formats:
  src=destination/'fixtures'/('records.'+fmt);target=destination/'variants'/'truncated'/src.name;target.parent.mkdir(parents=True,exist_ok=True)
  if fmt=='csv':
   lines=src.read_text(encoding='utf-8').splitlines();target.write_text('\n'.join(lines[:-1])+'\n'+lines[-1].split(',')[0]+',',encoding='utf-8')
  else:target.write_bytes(src.read_bytes()[:len(src.read_bytes())//2])
  plans.append((target,{'partition':partition,'case':'truncated','format':fmt,'relative_path':target.relative_to(root).as_posix(),'encoding':'utf-8' if fmt=='csv' else 'format_defined','decimal_locale':'invariant','input_rows':'malformed','required_fields_present':'unknown','expected_outcome':'reject_file','expected_inserted_rows':0,'truth_path':(destination/'canonical_ground_truth.csv').relative_to(root).as_posix(),'transformation':'deterministic byte truncation; CSV incomplete final required fields'}))
  jsonwrite(target.parent/(fmt+'_manifest.json'),{'files':[{'path':target.name,'decimal_locale':'invariant','encoding':'utf-8','delimiter':','}],'case':'truncated','expected_outcome':'reject_file'})
 for p,row in plans:
  row.update({'sha256':sha(p),'bytes':p.stat().st_size,'actual_encoding':row['encoding'],'xlsx_writer':xlsx_writer if row['format']=='xlsx' else 'n.a.'})
  if row['case']=='utf16_wrong_encoding':row['encoding']='utf-8'
  manifest.append(row)
 for row in manifest:
  row['license']='CC BY 4.0';row['license_url']=LICENSE;row['data_role']='controlled_format_fixture_from_public_data; record-level source_category retained'
 csvwrite(destination/'data_manifest.csv',manifest);jsonwrite(destination/'expected_outcomes.json',{'schema':FIELDS,'partition':partition,'truth_records':len(truth),'cases':manifest,'note':'Expected outcomes fixed before benchmark execution; never inferred from observed adapter behavior.'})
 refresh_global_manifest(root)
 return manifest
def refresh_global_manifest(root):
 allrows=[]
 for partition in ['base','late_json','holdout']:
  p=root/partition/'data_manifest.csv'
  if p.exists():
   with p.open(encoding='utf-8-sig',newline='') as f:allrows.extend(csv.DictReader(f))
 if allrows:csvwrite(root/'data_manifest.csv',allrows)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['register','base','holdout']);ap.add_argument('--data-root',type=Path,required=True);ap.add_argument('--legacy-public',type=Path);ap.add_argument('--node',type=Path);ap.add_argument('--artifact-modules',type=Path);ap.add_argument('--work',type=Path);ap.add_argument('--freeze-manifest',type=Path);ap.add_argument('--freeze-source-root',type=Path);ap.add_argument('--xlsx-writer',choices=['artifact','standard-ooxml'],default='standard-ooxml');ap.add_argument('--truth-only',action='store_true');ap.add_argument('--resume-transfer',action='store_true',help='Only retry a logged network failure with no saved holdout bytes or adapter evaluation');a=ap.parse_args();root=a.data_root.resolve();root.mkdir(parents=True,exist_ok=True);protocol=register(root)
 if a.mode=='register':metadata(root,a.legacy_public);print('Metadata and fixed protocol registered. No holdout data fetched.');return
 if a.mode=='base':
  rows,lineage,sources=select_base(a.legacy_public.resolve(),root/'raw'/'base');dest=root/'base';csvwrite(dest/'canonical_ground_truth.csv',rows,FIELDS);csvwrite(dest/'source_lineage.csv',lineage);csvwrite(root/'raw'/'base'/'raw_manifest.csv',sources)
 elif a.mode=='holdout':
  if not a.freeze_manifest or not a.freeze_source_root:raise RuntimeError('Holdout requires Final freeze manifest and source root.')
  freeze=json.loads(a.freeze_manifest.read_text(encoding='utf-8'));assert freeze.get('stage')=='final_six_adapter_freeze' and freeze.get('frozen_at_utc') and freeze.get('files')
  for item in freeze['files']:assert sha(a.freeze_source_root/item['path'])==item['sha256'],item['path']
  receipt=root/'holdout'/'acquisition_receipt.json'
  prior=None
  if receipt.exists():
   prior=json.loads(receipt.read_text(encoding='utf-8'))
   if not a.resume_transfer or prior.get('status')!='download_failed_before_data_saved' or (root/'raw'/'holdout'/'beijing_pm25.zip').exists() or (root/'holdout'/'first_evaluation_receipt.json').exists():raise RuntimeError('Holdout acquisition already occurred or is not a pure failed transfer; no adaptive replay permitted.')
   assert prior['freeze_manifest_sha256']==sha(a.freeze_manifest)
  (root/'holdout'/'final_freeze_at_acquisition.json').write_bytes(a.freeze_manifest.read_bytes())
  entry={'status':'acquisition_started','started_at_utc':utc(),'freeze_manifest_sha256':sha(a.freeze_manifest),'freeze_at_utc':freeze['frozen_at_utc'],'pre_registration_sha256':sha(root/'protocol_pre_registration.json'),'preparation_script_sha256':sha(Path(__file__)),'data_downloaded_before_gate':False}
  if prior:entry['prior_failed_transfers']=prior.get('prior_failed_transfers',[])+[prior]
  jsonwrite(receipt,entry)
  rawdir=root/'raw'/'holdout';rawdir.mkdir(parents=True,exist_ok=True);archive=rawdir/'beijing_pm25.zip'
  try:record=download(SOURCES['holdout']['download'],archive)
  except Exception as exc:
   entry.update({'status':'download_failed_before_data_saved','transfer_error':f'{type(exc).__name__}: {exc}','failed_at_utc':utc(),'saved_data_bytes':False,'adapter_runs':0});jsonwrite(receipt,entry);raise
  with zipfile.ZipFile(archive) as z:
   member=next(n for n in z.namelist() if Path(n).name==SOURCES['holdout']['member']);data=z.read(member)
  raw=rawdir/SOURCES['holdout']['member'];raw.write_bytes(data);info=SOURCES['holdout'];rows=[];lineage=[]
  for rownum,r in enumerate(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))),2):
   value=r['pm2.5']
   if not finite(value):continue
   rid=f'B{len(rows)+1:04d}';locator=f'https://archive.ics.uci.edu/dataset/381#{info["member"]}:row={rownum}:col=pm2.5';normalized=canonical_decimal(value);rows.append(dict(zip(FIELDS,[rid,'BeijingPM25','public_real','pm2.5','ug/m3',normalized,locator])));lineage.append({'record_id':rid,'source_member':member,'physical_row':rownum,'source_column':'pm2.5','original_value':value,'canonical_value':normalized,'source_sha256':sha(raw)})
   if len(rows)==120:break
  assert len(rows)==120;dest=root/'holdout';csvwrite(dest/'canonical_ground_truth.csv',rows,FIELDS);csvwrite(dest/'source_lineage.csv',lineage);jsonwrite(rawdir/'download_manifest.json',record);obj=json.loads(receipt.read_text(encoding='utf-8'));obj.update({'status':'downloaded_selected_no_adapter_run','download_finished_at_utc':utc(),'download':record,'raw_member_sha256':sha(raw),'selected_records':120});jsonwrite(receipt,obj)
 else:raise ValueError(a.mode)
 if a.truth_only:
  csvwrite(dest/'fixtures'/'records.csv',rows,FIELDS);jsonwrite(dest/'manifest.json',{'files':[{'path':'fixtures/records.csv','encoding':'utf-8','decimal_locale':'invariant','delimiter':','}],'case':'normal','expected_final_unique_rows':len(rows)});print('Truth and CSV ready; full fixture generation pending.');return
 manifests=generate(root,a.mode,rows,a.node,Path(__file__).parent/'build_xlsx.mjs',a.work,a.artifact_modules,include_json=a.mode=='holdout',xlsx_writer=a.xlsx_writer)
 if a.mode=='holdout':jsonwrite(root/'holdout'/'holdout_untouched.json',{'status':'downloaded_after_final_freeze_not_yet_evaluated','data_downloaded':True,'data_read':True,'adapter_runs':0,'receipt':'acquisition_receipt.json'})
 print(json.dumps({'partition':a.mode,'records':len(rows),'fixture_files':len(manifests),'truth_sha256':sha(dest/'canonical_ground_truth.csv')}))
if __name__=='__main__':main()
