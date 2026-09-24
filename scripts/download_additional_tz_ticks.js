const { getHistoricRates } = require('dukascopy-node');
const fs = require('fs');
const path = require('path');

const outDir = path.join(__dirname, '..', 'data', 'market', 'raw_ticks');
const rawTradesPath = path.join(__dirname, '..', 'data', 'raw', 'trades_raw.tsv');
const lines = fs.readFileSync(rawTradesPath, 'utf8').trim().split('\n');

// Candidate timezone offsets in hours
const tzOffsets = [0, 2, 3, -5, 8];

const requiredHours = new Set();

for (const line of lines) {
  if (!line.trim()) continue;
  const parts = line.split('\t');
  const openTime = parts[2];
  const closeTime = parts[3];

  for (const offset of tzOffsets) {
    // Under static offset: UTC = local - offset
    const oLocal = new Date(openTime.replace(' ', 'T') + 'Z');
    const cLocal = new Date(closeTime.replace(' ', 'T') + 'Z');

    const oUtc = new Date(oLocal.getTime() - offset * 3600000);
    const cUtc = new Date(cLocal.getTime() - offset * 3600000);

    const oHour = new Date(Math.floor(oUtc.getTime() / 3600000) * 3600000);
    const cHour = new Date(Math.floor(cUtc.getTime() / 3600000) * 3600000);

    requiredHours.add(oHour.toISOString());
    requiredHours.add(cHour.toISOString());
  }
}

// Filter out those already downloaded
const toDownload = Array.from(requiredHours).filter(isoStr => {
  const fname = `xauusd_ticks_${isoStr.replace(/[:.]/g, '-')}.json`;
  const fpath = path.join(outDir, fname);
  return !fs.existsSync(fpath) || fs.statSync(fpath).size < 10;
}).sort();

console.log(`Additional timezone comparison hours to download: ${toDownload.length}`);

async function downloadHour(isoStr) {
  const from = new Date(isoStr);
  const to = new Date(from.getTime() + 3600 * 1000);
  const fname = `xauusd_ticks_${isoStr.replace(/[:.]/g, '-')}.json`;
  const fpath = path.join(outDir, fname);

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
      if (completed % 100 === 0 || completed === total) {
        console.log(`Progress: ${completed}/${total} hours processed... (ticks: ${res.ticks || 0})`);
      }
    }
  }

  const pool = [];
  for (let c = 0; c < concurrency; c++) pool.push(next());
  await Promise.all(pool);
}

(async () => {
  if (toDownload.length > 0) {
    console.time('tzDownloadTime');
    await runPool(toDownload, 8, downloadHour);
    console.timeEnd('tzDownloadTime');
  }
  console.log('All candidate timezone tick blocks ready!');
})();
