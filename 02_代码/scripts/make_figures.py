"""Draw manuscript figures from complete, independently verified experiment tables."""
from pathlib import Path
import argparse,csv,json,shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import FixedLocator,FuncFormatter,NullFormatter
from audit_panel_alignment import require_matplotlib_panel_alignment

plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
 'font.size':8,'axes.labelsize':8,'axes.titlesize':9,'xtick.labelsize':8,'ytick.labelsize':8,
 'svg.fonttype':'none','pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False,
 'axes.linewidth':.7,'legend.frameon':False,'savefig.facecolor':'white'})
BLUE='#2F6180';LIGHT='#DFEBF1';GRAY='#647078';ORANGE='#A65D2C'
def read(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def save(fig,name,out):
 fig.canvas.draw()
 require_matplotlib_panel_alignment(fig,json_out=str(out/'qa'/f'{name}.alignment.json'),overlay_svg=str(out/'qa'/f'{name}.alignment.svg'),tolerance_pt=1.5,gutter_tolerance_pt=1.5,strict=True)
 fig.savefig(out/f'{name}.pdf',metadata={'Title':name,'Author':'','Creator':'','Producer':''})
 fig.savefig(out/f'{name}.svg')
 fig.savefig(out/f'{name}.png',dpi=600)
 fig.savefig(out/f'{name}.tiff',dpi=600,pil_kwargs={'compression':'tiff_lzw'})
 plt.close(fig)
def architecture(out):
 fig,ax=plt.subplots(figsize=(7.48,3.5));fig.subplots_adjust(left=.01,right=.99,bottom=.01,top=.99);ax.set_xlim(0,100);ax.set_ylim(0,47);ax.axis('off')
 def box(x,y,w,h,text,fill=LIGHT,edge=BLUE):
  ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.25,rounding_size=.6',facecolor=fill,edgecolor=edge,lw=.8));ax.text(x+w/2,y+h/2,text,ha='center',va='center',fontsize=8)
 def arrow(a,b,style='-'):
  ax.annotate('',xy=b,xytext=a,arrowprops={'arrowstyle':'->','color':GRAY,'lw':.9,'linestyle':style})
 nodes=[(1,'Public inputs\n6 declared formats'),(21,'DLL discovery\nIFormatPlugin'),(41,'Parse + validate\n7 canonical fields'),(61,'SQLite transaction\nRecords + sources'),(81,'Host readback\nHash + provenance')]
 for x,t in nodes:box(x,31,17,11,t)
 for x,_ in nodes[:-1]:arrow((x+17.4,36.5),(x+19.4,36.5))
 box(21,12,17,10,'Static registration\nSame parser sources',fill='#F0F1F2',edge=GRAY);arrow((29.5,22.4),(29.5,30.5),style='--')
 box(41,12,17,10,'Per-file quarantine\nOriginal bytes retained',fill='#F5E9DF',edge=ORANGE);arrow((49.5,30.5),(49.5,22.5))
 box(61,12,17,10,'Durable audit\nIntent + terminal /\nrestart reconciliation');arrow((69.5,30.5),(69.5,22.5))
 box(81,12,17,10,'External oracle\nIndependent SQLite\nreader + source truth',fill='#F0F1F2',edge=GRAY);arrow((89.5,30.5),(89.5,22.5),style='--')
 ax.text(1,5,'CSV / XLSX / SQLite / DOCX / PDF / JSON; PDF DLL invokes a Python text-extraction bridge.',fontsize=8,va='center')
 ax.text(1,1,'Managed exceptions are isolated per file. Plugins share the Host process; this is not a security sandbox.',fontsize=8,va='center')
 save(fig,'Figure_1_Architecture',out)
def correctness(analysis,out):
 rows=read(analysis/'correctness_by_format.csv');cols=['Partition','Format','Valid accepted','Invalid detected','Field matches','Complete trace']
 labels={'base':'Development','late_json':'Late extension','holdout':'Held-out'}
 fig,ax=plt.subplots(figsize=(7.48,4.05));fig.subplots_adjust(left=.01,right=.99,bottom=.01,top=.99);ax.set_xlim(0,100);ax.set_ylim(0,len(rows)+3.7);ax.axis('off')
 xs=[1,21,34,50,67,84]
 top=len(rows)+2.8
 for x,t in zip(xs,cols):ax.text(x,top,t,weight='bold',va='center',fontsize=8)
 ax.hlines(top-.5,0,100,color=GRAY,lw=.8)
 for i,r in enumerate(rows):
  y=top-1.2-i
  fields=int(r['field_comparisons']);ff=f"{int(r['field_matches']):,} / {fields:,}"
  format_label='SQLite' if r['format']=='sqlite' else r['format'].upper()
  values=[labels[r['partition']],format_label,f"{r['valid_accepted']} / {r['valid_files']}",f"{r['invalid_detected']} / {r['invalid_files']}",ff,f"{r['provenance_complete_files']} / {r['files_tested']}"]
  for x,t in zip(xs,values):ax.text(x,y,t,fontsize=8,va='center')
  if i<len(rows)-1 and rows[i+1]['partition']!=r['partition']:ax.hlines(y-.5,0,100,color='#BDC5CA',lw=.5)
 ax.hlines(1.5,0,100,color=GRAY,lw=.8)
 ax.text(1,.7,'Counts are prespecified file tests and repeated field checks; they are not independent research samples.',fontsize=8,va='center')
 save(fig,'Figure_2_Correctness',out)
 shutil.copy2(analysis/'correctness_by_format.csv',out/'source_data'/'Figure_2.csv')
def performance(analysis,out):
 pairs=read(analysis/'paired_overheads.csv');summ=read(analysis/'overhead_summary.csv');sizes=sorted({int(r['workload_records']) for r in pairs})
 allvals=[float(r['relative_wall_overhead_percent']) for r in pairs];allbounds=[float(r[k]) for r in summ for k in ['ci95_low','ci95_high']];low=min([0]+allvals+allbounds);high=max([0]+allvals+allbounds);pad=max(3,(high-low)*.09)
 fig,axes=plt.subplots(1,3,figsize=(7.48,2.95),sharey=True);fig.subplots_adjust(left=.11,right=.98,bottom=.25,top=.82,wspace=.19)
 for j,(ax,size) in enumerate(zip(axes,sizes)):
  for i,c in enumerate([1,4,8]):
   vals=[float(r['relative_wall_overhead_percent']) for r in pairs if int(r['workload_records'])==size and int(r['concurrency'])==c];assert len(vals)==12
   jitter=np.linspace(-.14,.14,len(vals));ax.scatter(i+jitter,vals,color=GRAY,alpha=.65,s=10,lw=0,zorder=2)
   r=next(r for r in summ if int(r['workload_records'])==size and int(r['concurrency'])==c);med=float(r['median']);lo=float(r['ci95_low']);hi=float(r['ci95_high'])
   ax.errorbar(i,med,yerr=np.array([[med-lo],[hi-med]]),fmt='o',ms=4,color=BLUE,lw=1.5,capsize=3,zorder=3)
  ax.axhline(0,lw=.8,ls='--',color=ORANGE,zorder=0);ax.set_xlim(-.45,2.45);ax.set_ylim(low-pad,high+pad);ax.set_xticks([0,1,2],['1','4','8']);ax.set_xlabel('Concurrent file workers');ax.set_title(f'{size:,} workload records',pad=10)
  ax.text(0,1.12,chr(97+j),transform=ax.transAxes,fontweight='bold',fontsize=10,ha='left');ax.grid(axis='y',color='#E9ECEE',lw=.5)
 axes[0].set_ylabel('Dynamic / static wall-time difference (%)')
 fig.text(.5,.055,'12 randomized process pairs per condition; points = pairs; blue = median and bootstrap 95% CI.',ha='center',fontsize=8)
 save(fig,'Figure_3_Paired_Performance',out)
 for n in ['paired_overheads.csv','overhead_summary.csv']:shutil.copy2(analysis/n,out/'source_data'/('Figure_3_'+n))
def faults(analysis,raw,out):
 groups=read(analysis/'fault_summary.csv');trials=json.loads((raw/'all_trials.json').read_text('utf-8'));fig,ax=plt.subplots(figsize=(7.48,4.1));fig.subplots_adjust(left=.37,right=.97,bottom=.2,top=.95)
 labels=[]
 mapping={'truncated_file':'Truncated file','missing_fields':'Missing required field','plugin_exception':'Managed plugin exception','duplicate_replay':'Idempotent replay','database_lock':'Database lock','transaction_interruption':'Transaction rollback + replay','process_termination':'Process termination'}
 stage_labels={'hold_before_commit':'before COMMIT','hold_after_commit':'after COMMIT'}
 for i,g in enumerate(groups):
  kind,stage=g['fault_class'],g['fault_stage'];assert kind in mapping,('unknown fault class',kind);label=mapping[kind]
  if stage:
   assert stage in stage_labels,('unknown fault stage',stage);label+=': '+stage_labels[stage]
  labels.append(label);rr=[r for r in trials if r['fault_class']==kind and r.get('fault_stage','')==stage];v=[r['elapsed_ms']/1000 for r in rr];assert len(v)==10 and all(np.isfinite(x) and x>0 for x in v)
  ax.scatter(v,i+np.linspace(-.13,.13,10),s=12,color=GRAY,alpha=.65,lw=0,zorder=2);med=float(g['whole_case_ms_median'])/1000;lo=float(g['whole_case_ms_ci95_low'])/1000;hi=float(g['whole_case_ms_ci95_high'])/1000
  ax.errorbar(med,i,xerr=np.array([[med-lo],[hi-med]]),fmt='o',color=BLUE,capsize=3,ms=4,lw=1.4,zorder=3)
 ax.set_yticks(range(len(groups)),labels);ax.invert_yaxis();ax.set_xscale('log');ax.set_xlabel('Whole-case elapsed time (s; logarithmic scale)');ax.grid(axis='x',color='#E9ECEE',lw=.5)
 xmin,xmax=ax.get_xlim();ticks=[m*10**e for e in range(-3,4) for m in [1,2,5] if xmin<=m*10**e<=xmax]
 ax.xaxis.set_major_locator(FixedLocator(ticks));ax.xaxis.set_major_formatter(FuncFormatter(lambda x,pos:f'{x:g}'));ax.xaxis.set_minor_formatter(NullFormatter())
 fig.text(.5,.065,'10 fresh trials per subcondition; points = trials; blue = median and bootstrap 95% CI.',ha='center',fontsize=8)
 fig.text(.5,.02,'Whole-case time includes setup and verification; recovery endpoints differ and are reported separately.',ha='center',fontsize=8)
 save(fig,'Figure_4_Fault_Outcomes',out);shutil.copy2(analysis/'fault_summary.csv',out/'source_data'/'Figure_4_summary.csv')
 with (out/'source_data'/'Figure_4_trials.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['fault_class','fault_stage','trial','elapsed_ms','recover_elapsed_ms','passed']);w.writeheader();w.writerows({k:r.get(k) for k in w.fieldnames} for r in trials)
def main():
 p=argparse.ArgumentParser();p.add_argument('--analysis',type=Path,required=True);p.add_argument('--faults',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);(a.output/'qa').mkdir(exist_ok=True);(a.output/'source_data').mkdir(exist_ok=True)
 for name in ['performance_verification.json','correctness_verification.json','fault_analysis.json']:
  report=json.loads((a.analysis/name).read_text('utf-8'));assert report.get('status')!='blocked',('analysis is blocked; stale tables must not be plotted',name)
 architecture(a.output);correctness(a.analysis,a.output);performance(a.analysis,a.output);faults(a.analysis,a.faults,a.output)
 print('Four figures exported with complete source data and rendered alignment reports.')
if __name__=='__main__':main()
