using System;using System.Collections.Generic;using System.IO;using System.Reflection;using Ingestion;
[assembly:AssemblyVersion("1.0.0.0")]
namespace Ingestion.Plugins {public sealed class XlsxPlugin:IFormatPlugin {public string Name{get{return "XlsxPlugin";}}public string Version{get{return "1.0.0";}}public bool CanHandle(string path){return Path.GetExtension(path).Equals(".xlsx",StringComparison.OrdinalIgnoreCase);}public IEnumerable<CanonicalRecord> Parse(ParseContext context){return AdapterHelpers.Xlsx(context);}}}
