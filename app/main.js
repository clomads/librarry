// Librarry: one touch window, one tab per media app.
const { app, BrowserWindow, ipcMain } = require('electron');
const { execFile } = require('child_process');
const path = require('path');

const STACKCTL = path.join(__dirname, '..', 'stack', 'stackctl.sh');

// Touch tab-drag crashes mutter 50.5 (same flag the Chrome launchers carry).
app.commandLine.appendSwitch('disable-features', 'TouchDragAndDrop');
app.setName('Librarry');
// Test snapshots get a throwaway profile so they never touch the real sessions/logins.
if (process.env.LIBRARY_SNAPSHOT) app.setPath('userData', process.env.LIBRARY_SNAPSHOT_PROFILE || require('fs').mkdtempSync(path.join(require('os').tmpdir(), 'librarry-test-')));
// One window only (the launcher closes an old copy first; this catches anything else).
else if (!app.requestSingleInstanceLock()) app.exit(0);

function stackctl(...args) {
  return new Promise((resolve, reject) => {
    execFile(STACKCTL, args, { timeout: 15 * 60 * 1000 }, (err, stdout, stderr) => {
      if (err) return reject(new Error((stderr || err.message).trim()));
      try { resolve(JSON.parse(stdout.trim().split('\n').pop())); } catch { resolve(stdout); }
    });
  });
}

ipcMain.handle('stack', (_e, args) => stackctl(...args));

// ---- tab badges: active items and errors, straight from each app's API ----
const fs = require('fs');
const CFG = path.join(require('os').homedir(), '.local/share/library-stack');
const arrKey = app => (fs.readFileSync(path.join(CFG, app, 'config.xml'), 'utf8').match(/<ApiKey>([^<]+)/) || [])[1];
const seerrKey = () => JSON.parse(fs.readFileSync(path.join(CFG, 'seerr/settings.json'), 'utf8')).main.apiKey;
async function getJson(url, headers) {
  const r = await fetch(url, { headers, signal: AbortSignal.timeout(8000) });
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}
let trSession = '';
async function transmission() {
  const body = JSON.stringify({ method: 'torrent-get', arguments: { fields: ['status', 'error'] } });
  for (let i = 0; i < 2; i++) {
    const r = await fetch('http://127.0.0.1:9091/transmission/rpc', { method: 'POST', body,
      headers: { 'X-Transmission-Session-Id': trSession }, signal: AbortSignal.timeout(8000) });
    if (r.status === 409) { trSession = r.headers.get('x-transmission-session-id'); continue; }
    const t = (await r.json()).arguments.torrents;
    // status 4 = downloading, 3 = queued to download
    return { count: t.filter(x => x.status === 4 || x.status === 3).length, error: t.filter(x => x.error).length };
  }
  throw new Error('transmission session');
}
async function arr(app, port, ver) {
  const h = { 'X-Api-Key': arrKey(app) };
  const [q, health] = await Promise.all([
    getJson(`http://127.0.0.1:${port}/api/${ver}/queue/status`, h),
    getJson(`http://127.0.0.1:${port}/api/${ver}/health`, h),
  ]);
  const errs = health.filter(x => x.type === 'error').length + (q.errors ? 1 : 0);
  return { count: q.totalCount, error: errs, warn: q.warnings || health.some(x => x.type === 'warning') };
}
async function prowlarr() {
  const h = { 'X-Api-Key': arrKey('prowlarr') };
  const [health, status] = await Promise.all([
    getJson('http://127.0.0.1:9696/api/v1/health', h),
    getJson('http://127.0.0.1:9696/api/v1/indexerstatus', h),
  ]);
  // count = indexers currently disabled after failures
  return { count: 0, error: health.filter(x => x.type === 'error').length + status.length };
}
async function requests() {
  const c = await getJson('http://127.0.0.1:5055/api/v1/request/count', { 'X-Api-Key': seerrKey() });
  return { count: c.pending, error: 0 };  // waiting for your approval
}
ipcMain.handle('badges', async () => {
  const jobs = {
    flood: transmission, requests,
    radarr: () => arr('radarr', 7878, 'v3'), sonarr: () => arr('sonarr', 8989, 'v3'),
    lidarr: () => arr('lidarr', 8686, 'v1'), whisparr: () => arr('whisparr', 6969, 'v3'),
    prowlarr,
  };
  const out = {};
  await Promise.all(Object.entries(jobs).map(async ([k, f]) => {
    try { out[k] = await f(); } catch { out[k] = { down: true }; }
  }));
  return out;
});
ipcMain.handle('versions', () => ({ app: app.getVersion(), electron: process.versions.electron }));

app.whenReady().then(() => {
  const win = new BrowserWindow({
    width: 1400, height: 900, backgroundColor: '#111114', title: 'Librarry',
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), webviewTag: true },
  });
  win.maximize();
  app.on('second-instance', () => { if (win.isMinimized()) win.restore(); win.show(); win.focus(); });
  // LIBRARY_DEMO=1 swaps real IP addresses for documentation ones (for README screenshots)
  win.loadFile('index.html', { hash: process.env.LIBRARY_TAB || '', query: process.env.LIBRARY_DEMO ? { demo: '1' } : {} });
  // LIBRARY_SNAPSHOT=/path.png: grab the window after a few seconds and quit (for testing).
  if (process.env.LIBRARY_SNAPSHOT) setTimeout(async () => {
    require('fs').writeFileSync(process.env.LIBRARY_SNAPSHOT, (await win.webContents.capturePage()).toPNG());
    app.quit();
  }, Number(process.env.LIBRARY_SNAPSHOT_DELAY || 8000));
  // Make sure the containers are running; tabs retry until their app answers.
  stackctl('up').catch(e => console.error('stack up failed:', e.message));
});

app.on('window-all-closed', () => app.quit());
