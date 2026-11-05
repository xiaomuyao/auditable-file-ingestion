using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
namespace Ingestion {
    public sealed class SqliteException : IOException {
        public int Code; public SqliteException(int code,string message):base("SQLITE_"+code+":"+message){Code=code;}
        public bool Transient {get{return (Code&255)==5||(Code&255)==6;}}
    }
    public sealed class NativeSqlite : IDisposable {
        [DllImport("winsqlite3.dll",CallingConvention=CallingConvention.Cdecl)] static extern int sqlite3_open_v2(byte[] file,out IntPtr db,int flags,IntPtr vfs);
        [DllImport("winsqlite3.dll",CallingConvention=CallingConvention.Cdecl)] static extern int sqlite3_close(IntPtr db);
        [DllImport("winsqlite3.dll",CallingConvention=CallingConvention.Cdecl)] static extern int sqlite3_exec(IntPtr db,byte[] sql,IntPtr cb,IntPtr data,out IntPtr err);
        [DllImport("winsqlite3.dll",CallingConvention=CallingConvention.Cdecl)] static extern int sqlite3_get_table(IntPtr db,byte[] sql,out IntPtr table,out int rows,out int columns,out IntPtr error);
        [DllImport("winsqlite3.dll",CallingConvention=CallingConvention.Cdecl)] static extern void sqlite3_free_table(IntPtr p);
        [DllImport("winsqlite3.dll",CallingConvention=CallingConvention.Cdecl)] static extern void sqlite3_free(IntPtr p);
        [DllImport("winsqlite3.dll",CallingConvention=CallingConvention.Cdecl)] static extern IntPtr sqlite3_libversion();
        IntPtr db;
        static byte[] Z(string s){return Encoding.UTF8.GetBytes(s+"\0");}
        static string Utf8(IntPtr p){if(p==IntPtr.Zero)return null;int n=0;while(Marshal.ReadByte(p,n)!=0)n++;byte[] b=new byte[n];Marshal.Copy(p,b,0,n);return Encoding.UTF8.GetString(b);}
        public static string Version {get{return Utf8(sqlite3_libversion());}}
        public static string Q(string s){return s==null?"NULL":"'"+s.Replace("'","''")+"'";}
        public NativeSqlite(string path,bool readOnly=false){int rc=sqlite3_open_v2(Z(path),out db,readOnly?1:6,IntPtr.Zero);if(rc!=0){Dispose();throw new SqliteException(rc,"open failed");}Exec("PRAGMA busy_timeout=0; PRAGMA foreign_keys=ON;");if(!readOnly)Exec("PRAGMA synchronous=FULL;");}
        public void Exec(string sql){IntPtr e;int rc=sqlite3_exec(db,Z(sql),IntPtr.Zero,IntPtr.Zero,out e);if(rc!=0){string s=Utf8(e);sqlite3_free(e);throw new SqliteException(rc,s);}}
        public List<Dictionary<string,string>> Query(string sql){IntPtr t,e;int n,m;int rc=sqlite3_get_table(db,Z(sql),out t,out n,out m,out e);if(rc!=0){string s=Utf8(e);sqlite3_free(e);throw new SqliteException(rc,s);}var result=new List<Dictionary<string,string>>();try{string[] names=new string[m];for(int c=0;c<m;c++)names[c]=Utf8(Marshal.ReadIntPtr(t,c*IntPtr.Size));for(int r=0;r<n;r++){var row=new Dictionary<string,string>();for(int c=0;c<m;c++)row[names[c]]=Utf8(Marshal.ReadIntPtr(t,((r+1)*m+c)*IntPtr.Size));result.Add(row);}}finally{sqlite3_free_table(t);}return result;}
        public string Scalar(string sql){var a=Query(sql);foreach(var r in a)foreach(var v in r.Values)return v;return null;}
        public void Dispose(){if(db!=IntPtr.Zero){sqlite3_close(db);db=IntPtr.Zero;}}
    }
}
