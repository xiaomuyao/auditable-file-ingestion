"""Controlled pipe-row PDF report adapter shared by both executables."""
import json
import sys
from pypdf import PdfReader

rows=[]
for page in PdfReader(sys.argv[1],strict=True).pages:
    for line in (page.extract_text() or '').splitlines():
        if not line.strip():
            continue
        rows.append(line.split('|'))
print(json.dumps(rows,ensure_ascii=True,separators=(',',':')))
