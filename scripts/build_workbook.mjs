import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const RUN_ID = "01a0bada-7e73-77c0-9b06-15db62fdf55d";
const OUTPUT_DIR = path.join(ROOT, "outputs", RUN_ID);
const TABLE_DIR = path.join(OUTPUT_DIR, "tables");
const PREVIEW_DIR = path.join(OUTPUT_DIR, "workbook_previews");
const OUTPUT_XLSX = path.join(OUTPUT_DIR, "reverse_trade_analysis.xlsx");

const COLORS = {
  navy: "#17365D",
  blue: "#1F4E78",
  paleBlue: "#D9EAF7",
  paleGold: "#FFF2CC",
  paleGray: "#F3F6F8",
  gray: "#5B6573",
  green: "#E2F0D9",
  red: "#FCE4D6",
  white: "#FFFFFF",
  text: "#1F2937",
  border: "#C8D2DC",
};

function parseDelimited(text, delimiter) {
  return text
    .replace(/^\uFEFF/, "")
    .trim()
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => line.split(delimiter));
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      row.push(cell);
      cell = "";
    } else if (char === "\n" && !quoted) {
      row.push(cell.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  if (cell.length > 0 || row.length > 0) {
    row.push(cell.replace(/\r$/, ""));
    rows.push(row);
  }
  return rows.filter((values) => values.some((value) => value !== ""));
}

async function readCsv(relativePath) {
  return parseCsv(await fs.readFile(path.join(ROOT, relativePath), "utf8"));
}

async function readTsv(relativePath) {
  return parseDelimited(await fs.readFile(path.join(ROOT, relativePath), "utf8"), "\t");
}

function columnLetter(column) {
  let number = column;
  let result = "";
  while (number > 0) {
    const remainder = (number - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    number = Math.floor((number - 1) / 26);
  }
  return result;
}

function asNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : value;
}

function asDate(value) {
  return new Date(`${value.replace(" ", "T")}Z`);
}

function styleTitle(sheet, title, subtitle, lastColumn) {
  const titleRange = sheet.getRange(`A1:${lastColumn}1`);
  titleRange.merge();
  titleRange.values = [[title]];
  titleRange.format = {
    fill: COLORS.navy,
    font: { name: "Arial", size: 15, bold: true, color: COLORS.white },
    horizontalAlignment: "left",
    verticalAlignment: "middle",
    rowHeight: 28,
  };
  const subtitleRange = sheet.getRange(`A2:${lastColumn}2`);
  subtitleRange.merge();
  subtitleRange.values = [[subtitle]];
  subtitleRange.format = {
    fill: COLORS.paleBlue,
    font: { name: "Arial", size: 10, italic: true, color: COLORS.gray },
    horizontalAlignment: "left",
    verticalAlignment: "middle",
    wrapText: true,
    rowHeight: 30,
  };
}

function styleHeader(range) {
  range.format = {
    fill: COLORS.blue,
    font: { name: "Arial", size: 10, bold: true, color: COLORS.white },
    horizontalAlignment: "center",
    verticalAlignment: "middle",
    wrapText: true,
    rowHeight: 24,
    borders: { preset: "all", style: "thin", color: COLORS.border },
  };
}

function styleSection(range) {
  range.format = {
    fill: COLORS.paleBlue,
    font: { name: "Arial", size: 10, bold: true, color: COLORS.navy },
    verticalAlignment: "middle",
    rowHeight: 20,
    borders: { bottom: { style: "thin", color: COLORS.blue } },
  };
}

function styleBody(range) {
  range.format = {
    font: { name: "Arial", size: 10, color: COLORS.text },
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: "#E2E8F0" },
  };
}

function writeTable(sheet, startRow, startColumn, rows, name) {
  const header = rows[0];
  const width = header.length;
  const topLeft = `${columnLetter(startColumn)}${startRow}`;
  sheet.getRange(topLeft).write(rows);
  const endColumn = columnLetter(startColumn + width - 1);
  const endRow = startRow + rows.length - 1;
  styleHeader(sheet.getRange(`${columnLetter(startColumn)}${startRow}:${endColumn}${startRow}`));
  if (rows.length > 1) {
    styleBody(sheet.getRange(`${columnLetter(startColumn)}${startRow + 1}:${endColumn}${endRow}`));
  }
  return {
    address: `${columnLetter(startColumn)}${startRow}:${endColumn}${endRow}`,
    endRow,
    endColumn,
    name,
  };
}

function setWidths(sheet, widths) {
  for (const [column, width] of Object.entries(widths)) {
    sheet.getRange(`${column}:${column}`).format.columnWidth = width;
  }
}

function rejectFormulaErrors(sheet, address) {
  const errors = [];
  const values = sheet.getRange(address).values;
  for (let rowIndex = 0; rowIndex < values.length; rowIndex += 1) {
    for (let columnIndex = 0; columnIndex < values[rowIndex].length; columnIndex += 1) {
      const value = values[rowIndex][columnIndex];
      if (typeof value === "string" && /^#(REF!|DIV\/0!|VALUE!|NAME\?|N\/A)/.test(value)) {
        errors.push({ row: rowIndex + 1, column: columnIndex + 1, value });
      }
    }
  }
  if (errors.length) {
    throw new Error(`Formula errors in ${sheet.name}!${address}: ${JSON.stringify(errors)}`);
  }
  return errors;
}

async function main() {
  await fs.mkdir(OUTPUT_DIR, { recursive: true });
  await fs.mkdir(PREVIEW_DIR, { recursive: true });

  const rawTrades = await readTsv("data/raw/trades_raw.tsv");
  const monthly = await readCsv(`outputs/${RUN_ID}/tables/temporal_monthly.csv`);
  const hourly = await readCsv(`outputs/${RUN_ID}/tables/temporal_hourly.csv`);
  const phases = await readCsv(`outputs/${RUN_ID}/tables/holding_time_phases.csv`);
  const experiments = await readCsv(`outputs/${RUN_ID}/tables/experiment_tracker.csv`);
  const proofLog = await readCsv(`outputs/${RUN_ID}/tables/proof_log.csv`);
  const candidateRanking = await readCsv(`outputs/${RUN_ID}/tables/candidate_ranking.csv`);
  const confidence = await readCsv(`outputs/${RUN_ID}/tables/confidence_table.csv`);
  const fieldDictionary = await readCsv(`outputs/${RUN_ID}/tables/field_dictionary.csv`);
  const gmm = await readCsv(`outputs/${RUN_ID}/tables/gmm_model_comparison.csv`);
  const hmm = await readCsv(`outputs/${RUN_ID}/tables/hmm_model_comparison.csv`);
  const research = await readTsv("research/source_matrix.tsv");
  const metrics = JSON.parse(
    await fs.readFile(path.join(TABLE_DIR, "..", "analysis_metrics.json"), "utf8"),
  );

  const workbook = Workbook.create();
  workbook.setColorScheme({
    name: "Forensic Research",
    themeColors: {
      accent1: COLORS.blue,
      accent2: "#2F75B5",
      accent3: "#70AD47",
      bg1: COLORS.white,
      tx1: COLORS.text,
    },
  });

  const summary = workbook.worksheets.add("Summary");
  const fingerprint = workbook.worksheets.add("Fingerprint");
  const experimentSheet = workbook.worksheets.add("Experiments");
  const evidence = workbook.worksheets.add("Evidence");
  const trades = workbook.worksheets.add("Trades");
  const sources = workbook.worksheets.add("Sources");
  const sheets = [summary, fingerprint, experimentSheet, evidence, trades, sources];
  for (const sheet of sheets) {
    sheet.showGridLines = false;
    sheet.tabColor = COLORS.blue;
  }
  evidence.tabColor = "#C55A11";
  trades.tabColor = "#548235";
  sources.tabColor = "#7F6000";

  // Inputs: source rows plus transparent row-level formulas.
  styleTitle(
    trades,
    "Supplied trade history — preserved values plus audit formulas",
    "Headerless TSV transcribed as typed values. Working field names are forensic labels, not verified broker semantics.",
    "L",
  );
  const tradeHeaders = [
    "Ticket", "Side", "Open time", "Close time", "Symbol", "Lot", "Observed price",
    "Reported result", "Holding min (formula)", "Positive result (formula)",
    "Result per 0.01 (formula)", "Concurrency at entry (formula)",
  ];
  const typedTrades = rawTrades.map((row) => [
    String(row[0]), row[1], asDate(row[2]), asDate(row[3]), row[4], asNumber(row[5]),
    asNumber(row[6]), asNumber(row[7]), null, null, null, null,
  ]);
  const tradeHeaderRow = 4;
  const tradeFirstRow = tradeHeaderRow + 1;
  const lastTradeRow = tradeFirstRow + typedTrades.length - 1;
  trades.getRange(`A${tradeHeaderRow}`).write([tradeHeaders, ...typedTrades]);
  trades.getRange(`I${tradeFirstRow}`).formulas = [[`=(D${tradeFirstRow}-C${tradeFirstRow})*1440`]];
  trades.getRange(`I${tradeFirstRow}:I${lastTradeRow}`).fillDown();
  trades.getRange(`J${tradeFirstRow}`).formulas = [[`=H${tradeFirstRow}>0`]];
  trades.getRange(`J${tradeFirstRow}:J${lastTradeRow}`).fillDown();
  trades.getRange(`K${tradeFirstRow}`).formulas = [[`=H${tradeFirstRow}/(F${tradeFirstRow}/0.01)`]];
  trades.getRange(`K${tradeFirstRow}:K${lastTradeRow}`).fillDown();
  trades.getRange(`L${tradeFirstRow}`).formulas = [[`=COUNTIFS($C$${tradeFirstRow}:$C$${lastTradeRow},\"<=\"&C${tradeFirstRow},$D$${tradeFirstRow}:$D$${lastTradeRow},\">\"&C${tradeFirstRow})`]];
  trades.getRange(`L${tradeFirstRow}:L${lastTradeRow}`).fillDown();
  styleHeader(trades.getRange(`A${tradeHeaderRow}:L${tradeHeaderRow}`));
  styleBody(trades.getRange(`A${tradeFirstRow}:L${lastTradeRow}`));
  trades.getRange(`C${tradeFirstRow}:D${lastTradeRow}`).setNumberFormat("yyyy-mm-dd hh:mm:ss");
  trades.getRange(`F${tradeFirstRow}:F${lastTradeRow}`).setNumberFormat("0.00");
  trades.getRange(`G${tradeFirstRow}:H${lastTradeRow}`).setNumberFormat("0.00;[Red](0.00);-");
  trades.getRange(`I${tradeFirstRow}:I${lastTradeRow}`).setNumberFormat("0.00");
  trades.getRange(`K${tradeFirstRow}:K${lastTradeRow}`).setNumberFormat("0.00;[Red](0.00);-");
  trades.getRange(`L${tradeFirstRow}:L${lastTradeRow}`).setNumberFormat("0");
  trades.getRange(`H${tradeFirstRow}:H${lastTradeRow}`).conditionalFormats.add("cellIs", {
    operator: "lessThan",
    formula: 0,
    format: { fill: COLORS.red, font: { color: "#9C0006" } },
  });
  trades.getRange(`H${tradeFirstRow}:H${lastTradeRow}`).conditionalFormats.add("cellIs", {
    operator: "greaterThan",
    formula: 0,
    format: { fill: COLORS.green, font: { color: "#375623" } },
  });
  const tradeTable = trades.tables.add(`A${tradeHeaderRow}:L${lastTradeRow}`, true, "TradesTable");
  tradeTable.showBandedColumns = false;
  trades.freezePanes.freezeRows(4);
  trades.freezePanes.freezeColumns(2);
  setWidths(trades, {
    A: 14, B: 10, C: 20, D: 20, E: 14, F: 9, G: 15, H: 17, I: 18, J: 18, K: 20, L: 22,
  });

  // Outputs: formula-linked overview and two native range-backed charts.
  styleTitle(
    summary,
    "Reverse-trade forensic analysis — evidence-graded overview",
    "Source: supplied 423-row trade export. Reported result is in unknown units and is not an account return.",
    "L",
  );
  summary.getRange("A4:C4").merge();
  summary.getRange("A4").values = [["Formula-linked source facts"]];
  styleSection(summary.getRange("A4:C4"));
  const kpis = [
    ["Rows", "=COUNT(Trades!$F$5:$F$427)", "Complete supplied records"],
    ["Buy rows", "=COUNTIF(Trades!$B$5:$B$427,\"Buy\")", "Sell rows = total less Buy"],
    ["Positive reported-result rows", "=COUNTIF(Trades!$H$5:$H$427,\">0\")", "Reported-result field only"],
    ["Positive-result share", "=COUNTIF(Trades!$H$5:$H$427,\">0\")/COUNT(Trades!$H$5:$H$427)", "Not an unbiased strategy win rate"],
    ["Reported-result total", "=SUM(Trades!$H$5:$H$427)", "Unknown result/currency/fee semantics"],
    ["Reported profit factor", "=SUMIF(Trades!$H$5:$H$427,\">0\",Trades!$H$5:$H$427)/-SUMIF(Trades!$H$5:$H$427,\"<0\",Trades!$H$5:$H$427)", "Descriptive only; not account performance"],
    ["Median holding minutes", "=MEDIAN(Trades!$I$5:$I$427)", "Formula derived from apparent open/close times"],
    ["Maximum concurrent intervals", "=MAX(Trades!$L$5:$L$427)", "Observed intervals, not full account exposure"],
    ["0.01 lot rows", "=COUNTIF(Trades!$F$5:$F$427,0.01)", "Dominant observed size"],
    ["Observed interval start", "=MIN(Trades!$C$5:$C$427)", "Timezone unknown"],
    ["Observed interval end", "=MAX(Trades!$C$5:$C$427)", "Timezone unknown"],
  ];
  summary.getRange("A5").write(kpis.map(([label, , note]) => [label, null, note]));
  summary.getRange("B5").formulas = kpis.map(([, formula]) => [formula]);
  styleBody(summary.getRange("A5:C15"));
  summary.getRange("A5:A15").format.font = { name: "Arial", size: 10, bold: true, color: COLORS.text };
  summary.getRange("B5:B15").format.fill = COLORS.paleGold;
  summary.getRange("B8").setNumberFormat("0.0%");
  summary.getRange("B9:B10").setNumberFormat("0.00;[Red](0.00);-");
  summary.getRange("B11:B13").setNumberFormat("0.00");
  summary.getRange("B14:B15").setNumberFormat("yyyy-mm-dd hh:mm:ss");

  summary.getRange("E4:L4").merge();
  summary.getRange("E4").values = [["Conclusion and identification boundary"]];
  styleSection(summary.getRange("E4:L4"));
  summary.getRange("E5:L10").merge();
  summary.getRange("E5").values = [[
    "Level 1 behavioral fingerprint only: short-horizon, mostly fixed-size XAUUSD.f trading with near-balanced directions, episodic size changes, rare same-side overlaps, and longer holding times for profitable reported-result rows. Exact entry and exit rules are not identified from selected closed trades.",
  ]];
  summary.getRange("E5:L10").format = {
    fill: COLORS.paleGray,
    font: { name: "Arial", size: 10, color: COLORS.text },
    wrapText: true,
    verticalAlignment: "top",
    borders: { preset: "all", style: "thin", color: COLORS.border },
  };
  summary.getRange("E12:L15").merge();
  summary.getRange("E12").values = [[
    "External M1 sensitivity check: a non-broker Dukascopy bid feed with an assumed UTC+3 shift matched timestamps but failed walk-forward entry replication (mean AUC 0.511; zero predicted test entries). It is not evidence for a breakout, indicator, stop, target, or broker feed.",
  ]];
  summary.getRange("E12:L15").format = {
    fill: COLORS.red,
    font: { name: "Arial", size: 10, color: "#9C0006" },
    wrapText: true,
    verticalAlignment: "top",
    borders: { preset: "all", style: "thin", color: "#E6B8AF" },
  };

  const monthlyRows = monthly.slice(1).map((row) => [row[0], asNumber(row[1]), asNumber(row[5])]);
  const monthlyTable = writeTable(summary, 20, 1, [["Month", "Trades", "Total reported result"], ...monthlyRows], "MonthlySummary");
  summary.getRange(`C21:C${monthlyTable.endRow}`).setNumberFormat("0.00;[Red](0.00);-");
  const monthChart = summary.charts.add("line", summary.getRange(monthlyTable.address));
  monthChart.setPosition("E20", "L34");
  monthChart.title = "Monthly trade count and reported result";
  monthChart.titleTextStyle.fontSize = 12;
  monthChart.titleTextStyle.typeface = "Arial";
  monthChart.legend = { position: "top", textStyle: { typeface: "Arial", fontSize: 9 } };
  monthChart.xAxis = { axisType: "textAxis", textStyle: { typeface: "Arial", fontSize: 9 } };
  monthChart.yAxis = { textStyle: { typeface: "Arial", fontSize: 9 } };

  const hourlyRows = hourly.slice(1).map((row) => [asNumber(row[0]), asNumber(row[1])]);
  const hourlyTable = writeTable(summary, 38, 1, [["Raw open hour", "Trades"], ...hourlyRows], "HourlySummary");
  const hourChart = summary.charts.add("bar", summary.getRange(hourlyTable.address));
  hourChart.setPosition("E38", "L62");
  hourChart.title = "Observed entries by raw-clock hour";
  hourChart.titleTextStyle.fontSize = 12;
  hourChart.titleTextStyle.typeface = "Arial";
  hourChart.legend = { position: "bottom", textStyle: { typeface: "Arial", fontSize: 9 } };
  hourChart.xAxis = { textStyle: { typeface: "Arial", fontSize: 9 } };
  hourChart.yAxis = { textStyle: { typeface: "Arial", fontSize: 9 } };
  summary.getRange("A65:L67").merge();
  summary.getRange("A65").values = [[
    "Use the report and evidence tabs for claim-level assumptions and alternatives. Highest-value next data: broker/server timezone, symbol specification, full order/deal/position history, actual bid/ask entry and exit prices, SL/TP changes, account equity, and broker-specific ticks.",
  ]];
  summary.getRange("A65:L67").format = {
    fill: COLORS.paleBlue,
    font: { name: "Arial", size: 10, italic: true, color: COLORS.navy },
    wrapText: true,
    verticalAlignment: "middle",
    borders: { preset: "all", style: "thin", color: COLORS.border },
  };
  setWidths(summary, { A: 27, B: 18, C: 31, D: 3, E: 16, F: 16, G: 16, H: 16, I: 16, J: 16, K: 16, L: 16 });
  summary.freezePanes.freezeRows(2);

  // Builds: behavior-first descriptive tables.
  styleTitle(
    fingerprint,
    "Behavioral fingerprint",
    "Registered trade-only summaries. Statistical support describes the export, not the hidden source code.",
    "K",
  );
  fingerprint.getRange("A4:D4").merge();
  fingerprint.getRange("A4").values = [["Observed behavioral pattern"]];
  styleSection(fingerprint.getRange("A4:D4"));
  const behaviorRows = [
    ["Direction", "214 Buy / 209 Sell", "IID vs first-order Markov p=0.625", "Supported as an observed sequence"],
    ["Holding time", "Median 7.62 minutes; 74.7% within 15 min", "Winner median 8.27 vs loser 2.93 min", "Persistent across primary phases"],
    ["Size", "401 at 0.01; 22 above base", "Larger sizes are time-clustered", "Causal sizing rule unresolved"],
    ["Overlap", "Three same-side near-simultaneous pairs", "Maximum observed concurrency = 2", "Could be split/scaled execution or shared signal"],
    ["Raw clock", "Hour 8 has 63 entries", "Clock distribution is non-uniform", "Timezone and opportunity exposure unknown"],
  ];
  writeTable(fingerprint, 5, 1, [["Feature", "Observed", "Test / comparison", "Interpretation"], ...behaviorRows], "BehaviorTable");
  fingerprint.getRange("A12:K12").merge();
  fingerprint.getRange("A12").values = [["Primary holding-time phases — descriptive segmentation, not source-code versions"]];
  styleSection(fingerprint.getRange("A12:K12"));
  const phaseRows = phases.slice(1).map((row) => [
    row[0], row[3].slice(0, 10), row[4].slice(0, 10), asNumber(row[5]), asNumber(row[7]),
    asNumber(row[9]), asNumber(row[10]), asNumber(row[11]),
  ]);
  const phaseTable = writeTable(fingerprint, 13, 1, [[
    "Phase", "Start", "End", "Trades", "Median min", "Winner median", "Loser median", "Log-duration difference",
  ], ...phaseRows], "PhaseTable");
  fingerprint.getRange(`E14:H${phaseTable.endRow}`).setNumberFormat("0.00");
  fingerprint.getRange("A21:K21").merge();
  fingerprint.getRange("A21").values = [["Latent-model caution"]];
  styleSection(fingerprint.getRange("A21:K21"));
  fingerprint.getRange("A22:K25").merge();
  fingerprint.getRange("A22").values = [[
    "GMM BIC declines through six components and HMM BIC is lowest at five states, but low silhouettes and boundary-seeking selection mean these are descriptive mixtures of observed timing/duration/result/gap features — not a count of algorithms, EAs, or market regimes.",
  ]];
  fingerprint.getRange("A22:K25").format = {
    fill: COLORS.paleGold,
    font: { name: "Arial", size: 10, color: COLORS.text },
    wrapText: true,
    verticalAlignment: "middle",
    borders: { preset: "all", style: "thin", color: COLORS.border },
  };
  setWidths(fingerprint, { A: 18, B: 18, C: 18, D: 32, E: 14, F: 15, G: 15, H: 21, I: 12, J: 12, K: 12 });
  fingerprint.freezePanes.freezeRows(2);

  // Experiments: registered hypotheses and model-selection diagnostics.
  styleTitle(
    experimentSheet,
    "Experiment register and model diagnostics",
    "Each experiment retains its question, method, evidence status and limitations. No searched rule is promoted without chronological validation.",
    "J",
  );
  const experimentTable = writeTable(experimentSheet, 4, 1, experiments, "ExperimentRegister");
  experimentSheet.getRange(`F5:F${experimentTable.endRow}`).setNumberFormat("0.0000");
  experimentSheet.getRange("A17:J17").merge();
  experimentSheet.getRange("A17").values = [["Descriptive latent-model comparison"]];
  styleSection(experimentSheet.getRange("A17:J17"));
  const gmmRows = gmm.slice(1).map((row) => ["GMM", asNumber(row[1]), asNumber(row[2]), asNumber(row[3]), asNumber(row[4]), asNumber(row[6])]);
  const hmmRows = hmm.slice(1).map((row) => ["Gaussian HMM", asNumber(row[0]), asNumber(row[3]), asNumber(row[4]), null, asNumber(row[6])]);
  const modelTable = writeTable(experimentSheet, 18, 1, [["Model", "Order", "AIC", "BIC", "Silhouette", "Minimum state/component"], ...gmmRows, ...hmmRows], "ModelDiagnostics");
  experimentSheet.getRange(`C19:E${modelTable.endRow}`).setNumberFormat("0.0");
  experimentSheet.getRange("H17:J17").merge();
  experimentSheet.getRange("H17").values = [["External reference-feed sensitivity check"]];
  styleSection(experimentSheet.getRange("H17:J17"));
  const externalRows = [
    ["Reference data", "Dukascopy bid-only M1; assumed UTC+3 shift"],
    ["Entry time matching", "423 / 423 nearby bars; this is not feed authentication"],
    ["Walk-forward mean AUC", "0.511"],
    ["Walk-forward precision / lift", "0.0000 / 0.00x"],
    ["Decision", "Failed entry replication — no rule family supported"],
  ];
  writeTable(experimentSheet, 18, 8, [["Item", "Result"], ...externalRows], "ExternalSensitivity");
  setWidths(experimentSheet, { A: 8, B: 29, C: 26, D: 34, E: 26, F: 12, G: 24, H: 24, I: 38, J: 15 });
  experimentSheet.freezePanes.freezeRows(2);

  // Evidence: candidates, confidence grades, and explicit alternatives.
  styleTitle(
    evidence,
    "Evidence, candidates and confidence",
    "A claim is separated from its test, assumption and plausible alternatives. Confidence measures evidence strength, not profitability.",
    "F",
  );
  evidence.getRange("A4:F4").merge();
  evidence.getRange("A4").values = [["Candidate strategy-family assessment"]];
  styleSection(evidence.getRange("A4:F4"));
  const candidateTable = writeTable(evidence, 5, 1, candidateRanking, "CandidateRanking");
  evidence.getRange(`A${candidateTable.endRow + 2}:C${candidateTable.endRow + 2}`).merge();
  evidence.getRange(`A${candidateTable.endRow + 2}`).values = [["Confidence by component"]];
  styleSection(evidence.getRange(`A${candidateTable.endRow + 2}:C${candidateTable.endRow + 2}`));
  const confidenceTable = writeTable(evidence, candidateTable.endRow + 3, 1, confidence, "ConfidenceTable");
  const proofStart = confidenceTable.endRow + 3;
  evidence.getRange(`A${proofStart}:F${proofStart}`).merge();
  evidence.getRange(`A${proofStart}`).values = [["Proof log — exact claim, evidence and alternatives"]];
  styleSection(evidence.getRange(`A${proofStart}:F${proofStart}`));
  writeTable(evidence, proofStart + 1, 1, proofLog, "ProofLog");
  setWidths(evidence, { A: 31, B: 38, C: 35, D: 36, E: 40, F: 18 });
  evidence.freezePanes.freezeRows(2);

  // Inputs and provenance: source field dictionary plus research matrix.
  styleTitle(
    sources,
    "Field semantics, research sources and required data",
    "URLs are recorded in the research matrix. The supplied TSV is preserved separately; its SHA-256 is recorded in the report and analysis metrics.",
    "O",
  );
  sources.getRange("A4:F4").merge();
  sources.getRange("A4").values = [["Working field dictionary"]];
  styleSection(sources.getRange("A4:F4"));
  const fieldTable = writeTable(sources, 5, 1, fieldDictionary, "FieldDictionary");
  sources.getRange(`A${fieldTable.endRow + 2}:O${fieldTable.endRow + 2}`).merge();
  sources.getRange(`A${fieldTable.endRow + 2}`).values = [["Research source matrix and transfer limits"]];
  styleSection(sources.getRange(`A${fieldTable.endRow + 2}:O${fieldTable.endRow + 2}`));
  writeTable(sources, fieldTable.endRow + 3, 1, research, "ResearchMatrix");
  setWidths(sources, {
    A: 8, B: 36, C: 30, D: 26, E: 15, F: 14, G: 18, H: 18, I: 16, J: 16,
    K: 16, L: 21, M: 42, N: 44, O: 48,
  });
  sources.freezePanes.freezeRows(2);

  workbook.recalculate();

  // Verification: inspect formulas, scan computed values for common Excel errors, and render every new sheet.
  const formulaInspection = await workbook.inspect({
    kind: "formula",
    sheetId: "Summary",
    range: "A5:C15",
    maxChars: 6000,
  });
  const formulaErrors = [
    ...rejectFormulaErrors(summary, "A5:C15"),
    ...rejectFormulaErrors(trades, `I${tradeFirstRow}:L${lastTradeRow}`),
  ];
  const validation = {
    workbook: path.basename(OUTPUT_XLSX),
    sheets: sheets.map((sheet) => sheet.name),
    sourceRows: typedTrades.length,
    formulaErrorCount: formulaErrors.length,
    summaryValues: summary.getRange("A5:B15").values,
    formulaInspection: typeof formulaInspection === "string" ? formulaInspection.slice(0, 6000) : formulaInspection,
  };
  await fs.writeFile(path.join(OUTPUT_DIR, "workbook_validation.json"), JSON.stringify(validation, null, 2));

  for (const sheet of sheets) {
    const preview = await workbook.render({ sheetName: sheet.name, autoCrop: "all", scale: 0.7, format: "png" });
    await fs.writeFile(
      path.join(PREVIEW_DIR, `${sheet.name.toLowerCase()}.png`),
      new Uint8Array(await preview.arrayBuffer()),
    );
  }

  const file = await SpreadsheetFile.exportXlsx(workbook);
  await file.save(OUTPUT_XLSX);
  console.log(JSON.stringify({ output: OUTPUT_XLSX, validation }, null, 2));
}

await main();
