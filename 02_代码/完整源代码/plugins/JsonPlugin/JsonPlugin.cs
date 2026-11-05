using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Web.Script.Serialization;
using Ingestion;
[assembly:AssemblyVersion("1.0.0.0")]
namespace Ingestion.Plugins {
    public sealed class JsonPlugin:IFormatPlugin {
        public string Name {get{return "JsonPlugin";}}
        public string Version {get{return "1.0.0";}}
        public bool CanHandle(string path){return Path.GetExtension(path).Equals(".json",StringComparison.OrdinalIgnoreCase);}
        public IEnumerable<CanonicalRecord> Parse(ParseContext context){
            string label=String.IsNullOrEmpty(context.Input.encoding)||context.Input.encoding=="utf-8-sig"?"utf-8":context.Input.encoding;
            var declared=Encoding.GetEncoding(label,EncoderFallback.ExceptionFallback,DecoderFallback.ExceptionFallback);
            using(var stream=File.OpenRead(context.FullPath)){
                byte[] prefix=new byte[3];int n=stream.Read(prefix,0,3);
                int bom=n>=2&&prefix[0]==255&&prefix[1]==254?1200:n>=2&&prefix[0]==254&&prefix[1]==255?1201:n>=3&&prefix[0]==239&&prefix[1]==187&&prefix[2]==191?65001:0;
                if(bom!=0&&bom!=declared.CodePage)throw new InvalidDataException("ENCODING_DECLARATION_BOM_MISMATCH");
            }
            string text;using(var reader=new StreamReader(context.FullPath,declared,true))text=reader.ReadToEnd();
            object payload=new JavaScriptSerializer{MaxJsonLength=int.MaxValue}.DeserializeObject(text);
            var envelope=payload as Dictionary<string,object>;
            if(envelope!=null){if(!envelope.ContainsKey("records"))throw new InvalidDataException("MISSING_JSON_RECORDS");payload=envelope["records"];}
            var array=payload as object[];
            if(array==null)throw new InvalidDataException("JSON_RECORD_ARRAY_REQUIRED");
            var result=new List<CanonicalRecord>();
            foreach(object item in array){
                var source=item as Dictionary<string,object>;
                if(source==null)throw new InvalidDataException("JSON_RECORD_OBJECT_REQUIRED");
                var fields=new Dictionary<string,string>();
                foreach(string name in Validator.Fields){
                    if(!source.ContainsKey(name))throw new InvalidDataException("MISSING_JSON_FIELD:"+name);
                    if(!(source[name] is string))throw new InvalidDataException("JSON_CANONICAL_FIELD_MUST_BE_STRING:"+name);
                    fields[name]=(string)source[name];
                }
                result.Add(Utilities.FromRow(fields));
            }
            return result;
        }
    }
}
