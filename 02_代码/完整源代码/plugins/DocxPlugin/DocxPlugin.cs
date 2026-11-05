using System;using System.Collections.Generic;using System.IO;using System.Reflection;using Ingestion;
[assembly:AssemblyVersion("1.0.0.0")]
namespace Ingestion.Plugins {public sealed class DocxPlugin:IFormatPlugin {public string Name{get{return "DocxPlugin";}}public string Version{get{return "1.0.0";}}public bool CanHandle(string path){return Path.GetExtension(path).Equals(".docx",StringComparison.OrdinalIgnoreCase);}public IEnumerable<CanonicalRecord> Parse(ParseContext context){return AdapterHelpers.Docx(context);}}}
