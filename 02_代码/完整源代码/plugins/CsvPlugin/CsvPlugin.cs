using System;using System.Collections.Generic;using System.IO;using System.Reflection;using Ingestion;
[assembly:AssemblyVersion("1.0.0.0")]
namespace Ingestion.Plugins {public sealed class CsvPlugin:IFormatPlugin {public string Name{get{return "CsvPlugin";}}public string Version{get{return "1.0.0";}}public bool CanHandle(string path){return Path.GetExtension(path).Equals(".csv",StringComparison.OrdinalIgnoreCase);}public IEnumerable<CanonicalRecord> Parse(ParseContext context){return AdapterHelpers.Csv(context);}}}
