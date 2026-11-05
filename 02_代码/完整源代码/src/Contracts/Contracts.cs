using System;
using System.Collections.Generic;
using System.Reflection;
[assembly: AssemblyVersion("1.0.0.0")]
namespace Ingestion {
    public sealed class CanonicalRecord {
        public string record_id, dataset, source_category, field, unit, value, source_locator;
    }
    public sealed class InputFile {
        public string path;
        public string decimal_locale="invariant";
        public string encoding="utf-8";
        public string delimiter=",";
    }
    public sealed class InputManifest { public List<InputFile> files; }
    public sealed class ParseContext {
        public InputFile Input; public string FullPath, PythonExecutable, PdfBridgePath;
    }
    public interface IFormatPlugin {
        string Name {get;}
        string Version {get;}
        bool CanHandle(string filePath);
        IEnumerable<CanonicalRecord> Parse(ParseContext context);
    }
}
