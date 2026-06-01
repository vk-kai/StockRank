const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const targetUrl = process.argv[2] || 'https://data.10jqka.com.cn/funds/hyzjl/field/buy/order/DESC/ajax/1/';
const port = Number(process.argv[3] || 9231);

function chromePath() {
  const candidates = [
    process.env.THS_BROWSER_PATH,
    process.env.CHROME_PATH,
    process.env.CHROMIUM_PATH,
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/microsoft-edge',
    '/usr/bin/microsoft-edge-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/snap/bin/chromium'
  ].filter(Boolean);
  return candidates.find(candidate => fs.existsSync(candidate));
}

function browserCommand(executable, profileDir) {
  const args = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profileDir}`,
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--no-first-run',
    '--disable-background-networking',
    '--window-position=-32000,-32000',
    '--window-size=1200,900',
    targetUrl
  ];

  if (process.platform !== 'win32' && !process.env.DISPLAY && fs.existsSync('/usr/bin/xvfb-run')) {
    return {
      command: '/usr/bin/xvfb-run',
      args: ['-a', '--server-args=-screen 0 1200x900x24', executable, ...args]
    };
  }

  return { command: executable, args };
}

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForJson(url, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return await response.json();
    } catch (error) {
      lastError = error;
    }
    await sleep(250);
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0;
    const pending = new Map();

    ws.onopen = () => {
      resolve({
        ws,
        send(method, params = {}) {
          return new Promise((res, rej) => {
            const messageId = ++id;
            pending.set(messageId, { res, rej });
            ws.send(JSON.stringify({ id: messageId, method, params }));
          });
        }
      });
    };
    ws.onerror = reject;
    ws.onmessage = event => {
      const message = JSON.parse(event.data);
      if (!message.id || !pending.has(message.id)) return;
      const callbacks = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) callbacks.rej(new Error(JSON.stringify(message.error)));
      else callbacks.res(message.result);
    };
  });
}

async function main() {
  const executable = chromePath();
  if (!executable) {
    throw new Error('Chromium browser executable not found. Set THS_BROWSER_PATH, or install chromium/google-chrome/microsoft-edge.');
  }

  const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ths-cookie-'));
  const browser = browserCommand(executable, profileDir);
  const chrome = spawn(browser.command, browser.args, {
    detached: false,
    stdio: 'ignore',
    windowsHide: true
  });

  let client;
  try {
    await waitForJson(`http://127.0.0.1:${port}/json/version`);
    const tabs = await waitForJson(`http://127.0.0.1:${port}/json`);
    const tab = tabs.find(item => item.url && item.url.includes('10jqka.com.cn')) || tabs[0];
    client = await connect(tab.webSocketDebuggerUrl);
    await client.send('Network.enable');
    await client.send('Page.enable');

    let cookie = '';
    let body = '';
    for (let i = 0; i < 12; i += 1) {
      await sleep(1000);
      const cookies = await client.send('Network.getAllCookies');
      const vCookie = cookies.cookies.find(item => item.name === 'v' && item.domain.includes('10jqka.com.cn'));
      const page = await client.send('Runtime.evaluate', {
        expression: 'document.body ? document.body.innerText.slice(0, 80) : ""',
        returnByValue: true
      }).catch(() => ({ result: { value: '' } }));
      body = page.result ? page.result.value : '';
      if (vCookie) {
        cookie = `${vCookie.name}=${vCookie.value}`;
        if (body && !body.includes('Nginx forbidden')) break;
      }
    }

    if (!cookie) {
      throw new Error(`THS v cookie not generated. Page preview: ${body}`);
    }
    process.stdout.write(cookie);
  } finally {
    if (client) {
      try {
        await client.send('Browser.close');
      } catch (_) {}
    }
    if (!chrome.killed) {
      chrome.kill();
    }
    try {
      fs.rmSync(profileDir, { recursive: true, force: true });
    } catch (_) {}
  }
}

main().catch(error => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
