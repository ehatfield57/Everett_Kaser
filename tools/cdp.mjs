// Minimal headless-Chrome driver over the DevTools protocol (no dependencies).
// usage: node cdp.mjs <url> <outdir> [steps.json]
// steps: [{"wait":ms} | {"shot":"name"} | {"click":[x,y],"button":"left"} | {"key":"a"} | {"eval":"js"} | {"move":[x,y]}
//         | {"sh":"shell command"} | {"goto":"url"}]
// PROFILE=<dir> keeps the browser profile (and anything the site stored) between runs.
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const [url, outdir, stepsFile] = process.argv.slice(2);
const steps = stepsFile ? JSON.parse(fs.readFileSync(stepsFile, 'utf8')) : [{ wait: 4000 }, { shot: 'shot' }];
fs.mkdirSync(outdir, { recursive: true });
const W = Number(process.env.W || 1280), H = Number(process.env.H || 800);
const profile = process.env.PROFILE || fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-'));
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
  '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, `--window-size=${W},${H}`,
  '--no-first-run', '--no-default-browser-check', '--autoplay-policy=no-user-gesture-required', 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });

const wsUrl = await new Promise((res, rej) => {
  let buf = '';
  chrome.stderr.on('data', (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\S+)/); if (m) res(m[1]); });
  setTimeout(() => rej(new Error('chrome did not start')), 15000);
});
const port = new URL(wsUrl).port;
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find((t) => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r));
let id = 0; const pending = new Map(); const logs = [];
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
  if (m.method === 'Runtime.consoleAPICalled') logs.push(`[${m.params.type}] ` + m.params.args.map((a) => a.value ?? a.description).join(' '));
  if (m.method === 'Runtime.exceptionThrown') logs.push('[exception] ' + JSON.stringify(m.params.exceptionDetails).slice(0, 800));
  if (m.method === 'Log.entryAdded') logs.push(`[log ${m.params.entry.level}] ${m.params.entry.text} ${m.params.entry.url || ''}`);
  if (m.method === 'Target.attachedToTarget') {
    // worker console output arrives through auto-attached sessions
  }
});
const cmd = (method, params = {}, sessionId) => new Promise((res) => {
  const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params, sessionId }));
});
await cmd('Runtime.enable'); await cmd('Log.enable'); await cmd('Page.enable');
await cmd('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });
await cmd('Page.navigate', { url });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function mouse(type, x, y, button = 'left', clickCount = 1) {
  await cmd('Input.dispatchMouseEvent', { type, x, y, button, clickCount, buttons: type === 'mousePressed' ? (button === 'right' ? 2 : 1) : 0 });
}
for (const s of steps) {
  if (s.wait) await sleep(s.wait);
  if (s.sh) { try { logs.push('[sh] ' + execSync(s.sh, { encoding: 'utf8' }).trim()); } catch (err) { logs.push('[sh failed] ' + err.message); } }
  if (s.goto) await cmd('Page.navigate', { url: s.goto });
  if (s.move) await mouse('mouseMoved', ...s.move, 'none');
  if (s.click) { const b = s.button || 'left'; await mouse('mouseMoved', ...s.click, 'none'); await mouse('mousePressed', ...s.click, b); await sleep(60); await mouse('mouseReleased', ...s.click, b); }
  if (s.key) { await cmd('Input.dispatchKeyEvent', { type: 'keyDown', key: s.key, windowsVirtualKeyCode: s.vk || s.key.toUpperCase().charCodeAt(0), text: s.text ?? s.key }); await cmd('Input.dispatchKeyEvent', { type: 'keyUp', key: s.key, windowsVirtualKeyCode: s.vk || s.key.toUpperCase().charCodeAt(0) }); }
  if (s.eval) { const r = await cmd('Runtime.evaluate', { expression: s.eval, returnByValue: true, awaitPromise: true }); logs.push('[eval] ' + JSON.stringify(r.result?.result?.value ?? r.result)); }
  if (s.shot) {
    const r = await cmd('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(outdir, s.shot + '.png'), Buffer.from(r.result.data, 'base64'));
  }
}
fs.writeFileSync(path.join(outdir, 'console.txt'), logs.join('\n'));
console.log(logs.join('\n'));
ws.close(); chrome.kill(); if (!process.env.PROFILE) { try { fs.rmSync(profile, { recursive: true, force: true }); } catch {} }
process.exit(0);
