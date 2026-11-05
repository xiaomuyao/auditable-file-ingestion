"""Hold a real SQLite writer lock and release it after a fixed delay."""
import argparse,json,os,sqlite3,time
from pathlib import Path

def durable(path,data):
    with Path(path).open('w',encoding='utf-8') as f:
        json.dump(data,f);f.flush();os.fsync(f.fileno())

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--ready',required=True);p.add_argument('--release-ms',type=int,default=300);p.add_argument('--result',required=True);a=p.parse_args()
    start=time.perf_counter();con=sqlite3.connect(a.db,timeout=0)
    con.execute('PRAGMA busy_timeout=0');con.execute('BEGIN IMMEDIATE')
    acquired=time.perf_counter();durable(a.ready,{'pid':os.getpid(),'state':'lock_acquired','monotonic_s':acquired,'release_ms':a.release_ms})
    time.sleep(a.release_ms/1000)
    con.rollback();released=time.perf_counter();con.close()
    durable(a.result,{'pid':os.getpid(),'state':'released','acquired_monotonic_s':acquired,'released_monotonic_s':released,'held_ms':(released-acquired)*1000,'source_modified':False})

if __name__=='__main__':main()
