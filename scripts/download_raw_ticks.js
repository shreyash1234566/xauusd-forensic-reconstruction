const { getHistoricRates } = require('dukascopy-node');
const fs = require('fs');
const path = require('path');

const outDir = path.join(__dirname, '..', 'data', 'market', 'raw_ticks');
if (!fs.existsSync(outDir)) {
  fs.mkdirSync(outDir, { recursive: true });
}

// Read raw trades TSV
const rawTradesPath = path.join(__dirname, '..', 'data', 'raw', 'trades_raw.tsv');
const tsvContent = fs.readFileSync(rawTradesPath, 'utf8');
const lines = tsvContent.trim().split('\n');

// Timezone conversion for EET/EEST DST
// In Greece / Eastern Europe (EET/EEST):
// DST begins last Sunday of March at 03:00 (shifts to UTC+3)
// DST ends last Sunday of October at 04:00 (shifts to UTC+2)
function getEetUtcOffset(dtStr) {
  const d = new Date(dtStr.replace(' ', 'T') + 'Z'); // parse as UTC reference for calendar calculation
  const year = d.getUTCFullYear();

  // Last Sunday of March
  const march31 = new Date(Date.UTC(year, 2, 31));
  const lastSunMarch = 31 - march31.getUTCDay();
  const dstStart = new Date(Date.UTC(year, 2, lastSunMarch, 1, 0, 0)); // 03:00 EET = 01:00 UTC

  // Last Sunday of October
  const oct31 = new Date(Date.UTC(year, 9, 31));
  const lastSunOct = 31 - oct31.getUTCDay();
  const dstEnd = new Date(Date.UTC(year, 9, lastSunOct, 1, 0, 0)); // 04:00 EEST = 01:00 UTC

  // Test local time
  // If dtStr is broker local time:
  // During DST (summer): UTC = Local - 3 hours
  // During Standard (winter): UTC = Local - 2 hours
  const localApprox = new Date(dtStr.replace(' ', 'T') + 'Z');
  const month = localApprox.getUTCMonth(); // 0-indexed

  if (month > 2 && month < 9) {
    return 3; // definitely summer (April - Sept)
  } else if (month < 2 || month > 9) {
    return 2; // definitely winter (Nov - Feb)
  } else if (month === 2) { // March
    const day = localApprox.getUTCDate();
    return (day >= lastSunMarch) ? 3 : 2;
  } else if (month === 9) { // October
    const day = localApprox.getUTCDate();
    return (day < lastSunOct) ? 3 : 2;
  }
  return 3;
}

function parseBrokerToUtc(dtStr) {
  const offset = getEetUtcOffset(dtStr);
  const localD = new Date(dtStr.replace(' ', 'T') + 'Z');
  return new Date(localD.getTime() - offset * 3600 * 1000);
}

const requiredHours = new Set();

for (const line of lines) {
  if (!line.trim()) continue;
  const parts = line.split('\t');
  const openTime = parts[2];
  const closeTime = parts[3];

  const openUtc = parseBrokerToUtc(openTime);
  const closeUtc = parseBrokerToUtc(closeTime);

  // Floor to hour
  let cur = new Date(Math.floor(openUtc.getTime() / 3600000) * 3600000);
  const end = new Date(Math.floor(closeUtc.getTime() / 3600000) * 3600000);

  while (cur.getTime() <= end.getTime()) {
    requiredHours.add(cur.toISOString());
    cur = new Date(cur.getTime() + 3600000);
  }
}

const sortedHours = Array.from(requiredHours).sort();
console.log(`Total unique hours to download: ${sortedHours.length}`);

// Download worker with concurrency pool
async function downloadHour(isoStr) {
  const from = new Date(isoStr);
  const to = new Date(from.getTime() + 3600 * 1000);
  const fname = `xauusd_ticks_${isoStr.replace(/[:.]/g, '-')}.json`;
  const fpath = path.join(outDir, fname);

  if (fs.existsSync(fpath) && fs.statSync(fpath).size > 10) {
    return { isoStr, status: 'cached', ticks: 0 };
  }

  try {
    const rates = await getHistoricRates({
      instrument: 'xauusd',
      dates: { from, to },
      timeframe: 'tick',
      volumes: true
    });
    fs.writeFileSync(fpath, JSON.stringify(rates));
    return { isoStr, status: 'downloaded', ticks: rates.length };
  } catch (err) {
    console.error(`Error downloading ${isoStr}:`, err.message);
    return { isoStr, status: 'error', error: err.message };
  }
}

async function runPool(items, concurrency, workerFn) {
  let index = 0;
  let completed = 0;
  const total = items.length;

  async function next() {
    while (index < items.length) {
      const i = index++;
      const res = await workerFn(items[i]);
      completed++;
      if (completed % 25 === 0 || completed === total) {
        console.log(`Progress: ${completed}/${total} hours processed... (last: ${res.status}, ticks: ${res.ticks || 0})`);
      }
    }
  }

  const pool = [];
  for (let c = 0; c < concurrency; c++) {
    pool.push(next());
  }
  await Promise.all(pool);
}

(async () => {
  console.time('totalDownloadTime');
  await runPool(sortedHours, 6, downloadHour);
  console.timeEnd('totalDownloadTime');
  console.log('All tick data acquired successfully!');
})();
