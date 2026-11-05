using Ingestion;using Ingestion.Plugins;
static class PluginFactory {public static string Mode="static";public static IFormatPlugin[] Create(Options o){return new IFormatPlugin[]{new CsvPlugin(),new XlsxPlugin(),new SqlitePlugin(),new DocxPlugin(),new PdfPlugin(),new JsonPlugin()};}}
