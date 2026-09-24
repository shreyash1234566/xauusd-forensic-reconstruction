import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const RUN_ID = "01a0bada-7e73-77c0-9b06-15db62fdf55d";
const OUTPUT_DIR = path.join(ROOT, "outputs", RUN_ID);
const workbookPath = path.join(OUTPUT_DIR, "reverse_trade_analysis.xlsx");

function collectErrorValues(values) {
  return values.flat().filter(
    (value) => typeof value === "string" && /^#(REF!|DIV\/0!|VALUE!|NAME\?|N\/A)/.test(value),
  );
}

const file = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(file);
workbook.recalculate();

const expectedSheets = ["Summary", "Fingerprint", "Experiments", "Evidence", "Trades", "Sources"];
const summary = workbook.worksheets.getItem("Summary");
const trades = workbook.worksheets.getItem("Trades");
const summaryValues = summary.getRange("A5:B15").values;
const errors = [
  ...collectErrorValues(summary.getRange("A5:C15").values),
  ...collectErrorValues(trades.getRange("I5:L427").values),
];
const inspection = await workbook.inspect({
  kind: "workbook,sheet,table,formula,chart",
  maxChars: 12000,
});
const verified = {
  expectedSheets,
  summaryValues,
  formulaErrorCount: errors.length,
  inspection,
};
if (errors.length) {
  throw new Error(`Formula errors found after XLSX import: ${errors.join(", ")}`);
}
await fs.writeFile(path.join(OUTPUT_DIR, "xlsx_import_verification.json"), JSON.stringify(verified, null, 2));
console.log(JSON.stringify({ sheets: expectedSheets, formulaErrorCount: errors.length, summaryValues }, null, 2));
