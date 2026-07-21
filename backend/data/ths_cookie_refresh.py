import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket


TARGET_URL = sys.argv[1] if len(sys.argv) > 1 else 'https://data.10jqka.com.cn/funds/hyzjl/field/buy/order/DESC/ajax/1/'


def browser_path():
    candidates = [
        os.environ.get('THS_BROWSER_PATH'),
        os.environ.get('CHROME_PATH'),
        os.environ.get('CHROMIUM_PATH'),
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/microsoft-edge',
        '/usr/bin/microsoft-edge-stable',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        '/snap/bin/chromium',
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(('127.0.0.1', 0))
        return server.getsockname()[1]


def fetch_json(url, timeout=20, debug=lambda: ''):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    debug_text = debug()
    message = str(last_error) if last_error else f'timed out waiting for {url}'
    if debug_text:
        message = f'{message}\nBrowser debug:\n{debug_text}'
    raise RuntimeError(message)


class CdpClient:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=8)
        self.next_id = 0

    def send(self, method, params=None):
        self.next_id += 1
        message_id = self.next_id
        self.ws.send(json.dumps({
            'id': message_id,
            'method': method,
            'params': params or {}
        }))
        while True:
            message = json.loads(self.ws.recv())
            if message.get('id') != message_id:
                continue
            if 'error' in message:
                raise RuntimeError(json.dumps(message['error'], ensure_ascii=False))
            return message.get('result', {})

    def close(self):
        self.ws.close()


def browser_command(executable, port, profile_dir):
    args = [
        f'--remote-debugging-address=127.0.0.1',
        f'--remote-debugging-port={port}',
        '--remote-allow-origins=*',
        f'--user-data-dir={profile_dir}',
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--no-first-run',
        '--disable-background-networking',
        '--window-position=-32000,-32000',
        '--window-size=1200,900',
        TARGET_URL,
    ]
    if os.name != 'nt' and not os.environ.get('DISPLAY') and os.path.exists('/usr/bin/xvfb-run'):
        if not shutil.which('xauth'):
            raise RuntimeError('xvfb-run is installed but xauth is missing. Install xauth in the backend image.')
        return ['/usr/bin/xvfb-run', '-a', '--server-args=-screen 0 1200x900x24', executable, *args]
    return [executable, *args]


def main():
    executable = browser_path()
    if not executable:
        raise RuntimeError('Chromium browser executable not found. Set THS_BROWSER_PATH, or install chromium/google-chrome/microsoft-edge.')

    port = free_port()
    profile_dir = tempfile.mkdtemp(prefix='ths-cookie-')
    cmd = browser_command(executable, port, profile_dir)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    stderr_chunks = []
    client = None

    def debug():
        if proc.stderr:
            try:
                chunk = proc.stderr.read()
                if chunk:
                    stderr_chunks.append(chunk)
            except Exception:
                pass
        status = proc.poll()
        stderr_text = ''.join(stderr_chunks)[-4000:]
        return '\n'.join(part for part in [
            'command=' + ' '.join(cmd),
            f'exit={status}' if status is not None else None,
            stderr_text.strip()
        ] if part)

    try:
        fetch_json(f'http://127.0.0.1:{port}/json/version', timeout=20, debug=debug)
        tabs = fetch_json(f'http://127.0.0.1:{port}/json', timeout=10, debug=debug)
        tab = next((item for item in tabs if '10jqka.com.cn' in item.get('url', '')), tabs[0])
        client = CdpClient(tab['webSocketDebuggerUrl'])
        client.send('Network.enable')
        client.send('Page.enable')

        cookie = ''
        body = ''
        for _ in range(12):
            time.sleep(1)
            cookies = client.send('Network.getAllCookies').get('cookies', [])
            v_cookie = next((item for item in cookies if item.get('name') == 'v' and '10jqka.com.cn' in item.get('domain', '')), None)
            page = client.send('Runtime.evaluate', {
                'expression': 'document.body ? document.body.innerText.slice(0, 80) : ""',
                'returnByValue': True
            })
            body = page.get('result', {}).get('value', '')
            if v_cookie:
                cookie = f"{v_cookie['name']}={v_cookie['value']}"
                if body and 'Nginx forbidden' not in body:
                    break

        if not cookie:
            raise RuntimeError(f'THS v cookie not generated. Page preview: {body}')
        sys.stdout.write(cookie)
    finally:
        if client:
            try:
                client.send('Browser.close')
            except Exception:
                pass
            client.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        sys.stderr.write(str(exc))
        sys.exit(1)
