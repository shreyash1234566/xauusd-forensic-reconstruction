// Resumable Dukascopy tick acquisition into an append-only supplemental store.
// This never writes to data/market/raw_ticks, the canonical archived source.

const fs = require('node:fs');
const path = require('node:path');
const { getHistoricRates } = require('dukascopy-node');

function parseArgs(argv) {
  const result = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i];
    if (!key.startsWith('--') || argv[i + 1] === undefined) throw new Error(`Expected --key value, got ${key}`);
    result[key.slice(2)] = argv[i + 1];
  }
  for (const key of ['start-utc', 'end-utc', 'output', 'limit']) {
    if (!result[key]) throw new Error(`Required argument missing: --${key}`);
  }
  return result;
}

function utcDate(value, name) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime()) || !/(Z|[+-]\d\d:\d\d)$/.test(value)) {
    throw new Error(`${name} must be an ISO timestamp with an explicit timezone`);
  }
  return date;
}

function hourKey(date) {
  const iso = new Date(date).toISOString();
  return iso.slice(0, 13).replace(/:/g, '-') + '-00-00-000Z';
}

function parseLimit(value) {
  if (value === 'all') return Infinity;
  const limit = Number.parseInt(value, 10);
  if (!Number.isInteger(limit) || limit < 1) throw new Error('--limit must be a positive integer or all');
  return limit;
}

async function main() {
  const args = parseArgs(process.argv);
  const start = utcDate(args['start-utc'], '--start-utc');
  const end = utcDate(args['end-utc'], '--end-utc');
  if (end < start) throw new Error('--end-utc must not precede --start-utc');
  const limit = parseLimit(args.limit);
  const includeCanonicalHours = args['include-canonical-hours'] === 'true';
  const output = path.resolve(args.output);
  const canonical = path.resolve(__dirname, '..', 'data', 'market', 'raw_ticks');
  if (output === canonical || output.startsWith(canonical + path.sep)) {
    throw new Error('Supplemental output must be separate from the canonical raw_ticks directory');
  }
  fs.mkdirSync(output, { recursive: true });
  const logPath = path.join(output, 'acquisition_log.jsonl');
  const hours = [];
  const cursor = new Date(start);
  cursor.setUTCMinutes(0, 0, 0);
  const last = new Date(end);
  last.setUTCMinutes(0, 0, 0);
  for (; cursor <= last; cursor.setUTCHours(cursor.getUTCHours() + 1)) {
    const hour = new Date(cursor);
    const file = `xauusd_ticks_${hourKey(hour)}.json`;
    const existingCanonical = path.join(canonical, file);
    const existingSupplemental = path.join(output, file);
    const goodCanonical = fs.existsSync(existingCanonical) && fs.statSync(existingCanonical).size > 10;
    const alreadyDownloaded = fs.existsSync(existingSupplemental);
    if ((includeCanonicalHours || !goodCanonical) && !alreadyDownloaded) hours.push({ hour, file });
  }
  const selected = hours.slice(0, limit);
  const concurrency = Math.max(1, Math.min(4, Number.parseInt(args.concurrency || '2', 10)));
  let next = 0;
  let complete = 0;
  let downloaded = 0;
  let failed = 0;
  const worker = async () => {
    while (true) {
      const index = next++;
      if (index >= selected.length) return;
      const item = selected[index];
      const from = item.hour;
      const to = new Date(from.getTime() + 60 * 60 * 1000);
      const destination = path.join(output, item.file);
      let status = 'error';
      let tickCount = 0;
      let error = null;
      let attemptsMade = 0;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        attemptsMade = attempt + 1;
        const temporary = `${destination}.${process.pid}.${attempt}.partial`;
        try {
          const rates = await getHistoricRates({
            instrument: 'xauusd',
            dates: { from, to },
            timeframe: 'tick',
            volumes: true,
          });
          if (!Array.isArray(rates)) throw new Error('Provider response was not an array');
          const serialized = JSON.stringify(rates);
          fs.writeFileSync(temporary, serialized, { flag: 'wx' });
          fs.renameSync(temporary, destination);
          tickCount = rates.length;
          status = tickCount ? 'downloaded' : 'empty_provider_response';
          error = null;
          break;
        } catch (caught) {
          if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
          error = String(caught && caught.message ? caught.message : caught);
          if (attempt < 2) await new Promise(resolve => setTimeout(resolve, 1000 * (2 ** attempt)));
        }
      }
      if (status === 'downloaded') downloaded += 1;
      else failed += 1;
      complete += 1;
      fs.appendFileSync(logPath, JSON.stringify({
        hour_utc: from.toISOString(), file: item.file, status, tick_count: tickCount,
        attempts: attemptsMade, error,
      }) + '\n');
      if (complete % 10 === 0 || complete === selected.length) {
        process.stdout.write(`Processed ${complete}/${selected.length}; downloaded=${downloaded}; empty_or_failed=${failed}\n`);
      }
    }
  };
  await Promise.all(Array.from({ length: concurrency }, worker));
  const summary = {
    provider: 'dukascopy-node',
    start_utc: start.toISOString(), end_utc: end.toISOString(),
    candidate_missing_hours: hours.length, selected_hours: selected.length,
    downloaded_hours: downloaded, empty_or_failed_hours: failed,
    concurrency, include_canonical_hours: includeCanonicalHours,
    canonical_raw_ticks_modified: false,
  };
  const priorLogs = fs.existsSync(logPath)
    ? fs.readFileSync(logPath, 'utf8').split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line))
    : [];
  for (const entry of priorLogs) {
    const key = `logged_${entry.status}_hours`;
    summary[key] = (summary[key] || 0) + 1;
  }
  summary.total_stored_hour_files = fs.readdirSync(output).filter(name => /^xauusd_ticks_.*\.json$/.test(name)).length;
  fs.writeFileSync(path.join(output, 'acquisition_summary.json'), JSON.stringify(summary, null, 2) + '\n');
  process.stdout.write(JSON.stringify(summary, null, 2) + '\n');
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
