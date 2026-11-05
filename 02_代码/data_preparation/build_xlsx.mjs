import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const spec=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
for(let i=0;i<spec.jobs.length;i++){
 const job=spec.jobs[i],wb=Workbook.create(),sh=wb.worksheets.add('Canonical');
 const rows=[job.headers,...job.rows];
 sh.getRangeByIndexes(0,0,rows.length,job.headers.length).values=rows;
 const all=sh.getRangeByIndexes(0,0,rows.length,job.headers.length);all.format.font={name:'Arial',size:9};all.format.columnWidth=19;all.format.rowHeight=20;all.setNumberFormat('@');
 const header=sh.getRangeByIndexes(0,0,1,job.headers.length);header.format.fill='#243E57';header.format.font={name:'Arial',bold:true,color:'#FFFFFF',size:9};header.format.rowHeight=28;
 const li=job.headers.indexOf('source_locator');if(li>=0)sh.getRangeByIndexes(0,li,rows.length,1).format.columnWidth=95;
 const ci=job.headers.indexOf('source_category');if(ci>=0)sh.getRangeByIndexes(0,ci,rows.length,1).format.columnWidth=22;
 sh.freezePanes.freezeRows(1);wb.recalculate();
 const inspect=await wb.inspect({kind:'table',range:'Canonical!A1:G4',include:'values,formulas',tableMaxRows:4,tableMaxCols:7});
 const output=await SpreadsheetFile.exportXlsx(wb);await output.save(job.path);
 if(i===0&&spec.preview){const b=await wb.render({sheetName:'Canonical',range:'A1:G5',scale:1.2,format:'png'});await fs.writeFile(spec.preview,new Uint8Array(await b.arrayBuffer()));}
 console.log(JSON.stringify({path:job.path,rows:job.rows.length,columns:job.headers.length,inspection:inspect.ndjson}));
}
