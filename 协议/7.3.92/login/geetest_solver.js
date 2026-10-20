
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');

function tryRequirePlaywright(id) {
  try {
    const mod = require(id);
    return mod && mod.chromium ? mod : null;
  } catch (e) {
    return null;
  }
}

function resolvePlaywright() {
  if (process.env.PLAYWRIGHT_PATH) {
    const mod = tryRequirePlaywright(process.env.PLAYWRIGHT_PATH);
    if (mod) return mod;
    console.warn('警告: 从 PLAYWRIGHT_PATH 加载失败:', process.env.PLAYWRIGHT_PATH);
  }

  for (const id of ['playwright', 'playwright-core']) {
    const mod = tryRequirePlaywright(id);
    if (mod) return mod;
  }

  const candidates = [
    path.join(__dirname, 'node_modules', 'playwright'),
    path.join(__dirname, 'node_modules', 'playwright-core'),
    path.join(__dirname, '..', 'node_modules', 'playwright'),
    path.join(__dirname, '..', 'node_modules', 'playwright-core'),
    'D:/Work/Tools/Node/npm-global/node_modules/@playwright/mcp/node_modules/playwright',
    'D:/Work/Tools/Node/npm-global/node_modules/playwright',
  ];

  // npm 全局安装目录（Windows: %APPDATA%\npm\node_modules）
  const globalRoots = [];
  if (process.env.APPDATA) {
    globalRoots.push(path.join(process.env.APPDATA, 'npm', 'node_modules'));
  }
  if (process.env.LOCALAPPDATA) {
    globalRoots.push(path.join(process.env.LOCALAPPDATA, 'npm', 'node_modules'));
  }
  for (const root of globalRoots) {
    candidates.push(path.join(root, 'playwright'));
    candidates.push(path.join(root, 'playwright-core'));
    candidates.push(path.join(root, '@playwright', 'mcp', 'node_modules', 'playwright'));
    candidates.push(path.join(root, '@playwright', 'cli', 'node_modules', 'playwright-core'));
  }

  for (const fb of candidates) {
    if (fs.existsSync(fb)) {
      const mod = tryRequirePlaywright(fb);
      if (mod) return mod;
    }
  }

  throw new Error('未找到 playwright 模块。请运行 npm install playwright 或配置 PLAYWRIGHT_PATH / NODE_PATH 环境变量。');
}

const { chromium } = resolvePlaywright();

function resolveChromiumExecutable() {
  const envPath = process.env.CHROMIUM_PATH || process.env.CHROME_BIN || process.env.CHROME_PATH;
  if (envPath && fs.existsSync(envPath)) {
    return envPath;
  }

  const devFallback = 'D:/Work/Tools/BrowserMCP/Playwright/browsers/chromium-1243/chrome-win64/chrome.exe';
  if (fs.existsSync(devFallback)) {
    return devFallback;
  }

  // 复用 Playwright 已下载的 Chromium（跨平台）
  const browserRoots = [];
  if (process.env.PLAYWRIGHT_BROWSERS_PATH) {
    browserRoots.push(process.env.PLAYWRIGHT_BROWSERS_PATH);
  }
  if (process.env.LOCALAPPDATA) {
    browserRoots.push(path.join(process.env.LOCALAPPDATA, 'ms-playwright'));
  }
  browserRoots.push(path.join(process.env.HOME || '', '.cache', 'ms-playwright'));
  for (const root of browserRoots) {
    if (!root || !fs.existsSync(root)) continue;
    let entries = [];
    try {
      entries = fs.readdirSync(root).filter(name => name.startsWith('chromium-'));
    } catch (e) {}
    for (const entry of entries) {
      const candidates = [
        path.join(root, entry, 'chrome-win64', 'chrome.exe'),
        path.join(root, entry, 'chrome-win', 'chrome.exe'),
        path.join(root, entry, 'chrome-linux', 'chrome'),
        path.join(root, entry, 'chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'),
      ];
      for (const candidate of candidates) {
        if (fs.existsSync(candidate)) return candidate;
      }
    }
  }

  // 系统已安装的 Chrome / Edge
  const systemCandidates = [];
  if (process.env.PROGRAMFILES) {
    systemCandidates.push(path.join(process.env.PROGRAMFILES, 'Google', 'Chrome', 'Application', 'chrome.exe'));
    systemCandidates.push(path.join(process.env.PROGRAMFILES, 'Microsoft', 'Edge', 'Application', 'msedge.exe'));
  }
  if (process.env['PROGRAMFILES(X86)']) {
    systemCandidates.push(path.join(process.env['PROGRAMFILES(X86)'], 'Google', 'Chrome', 'Application', 'chrome.exe'));
    systemCandidates.push(path.join(process.env['PROGRAMFILES(X86)'], 'Microsoft', 'Edge', 'Application', 'msedge.exe'));
  }
  if (process.env.LOCALAPPDATA) {
    systemCandidates.push(path.join(process.env.LOCALAPPDATA, 'Google', 'Chrome', 'Application', 'chrome.exe'));
  }
  systemCandidates.push(
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
  );
  for (const sp of systemCandidates) {
    if (fs.existsSync(sp)) {
      return sp;
    }
  }

  return undefined;
}

const HTML_CONTENT = `<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>GeeTest v4 Bridge</title>
    <script src="/gt4.js"></script>
    <style>
        body { margin: 0; padding: 20px; background: #fff; }
    </style>
</head>
<body>
    <div id="captcha-container"></div>
    <script>
        window.gt4Result = null;
        window.gt4Error = null;
        window.gt4Ready = false;
        
        function initCaptcha(captchaId) {
            initGeetest4({
                captchaId: captchaId,
                product: 'bind',
                language: 'zh'
            }, function (captcha) {
                window.captchaObj = captcha;
                captcha.onReady(function(){
                    window.gt4Ready = true;
                    console.log("GEETEST_READY");
                }).onSuccess(function(){
                    var result = captcha.getValidate();
                    window.gt4Result = result;
                    console.log("GEETEST_RESULT:" + JSON.stringify(result));
                }).onError(function(e){
                    window.gt4Error = e;
                    console.log("GEETEST_ERROR:" + JSON.stringify(e));
                });
            });
        }
    </script>
</body>
</html>`;

function generateHumanTrack(distance) {
  const track = [];
  const nPoints = Math.floor(Math.random() * 18) + 48; // 48 - 65
  const totalTime = Math.random() * 0.4 + 0.85; // 0.85 - 1.25s
  const k = Math.random() * 1.8 + 7.8;
  const t0 = Math.random() * 0.06 + 0.40;
  
  const arcHeight = (Math.random() - 0.5) * 2.4;
  let prevX = 0;
  let prevY = 0;
  const dtBase = totalTime / nPoints;

  for (let i = 1; i <= nPoints; i++) {
    const t = i / nPoints;
    let sig = 1 / (1 + Math.exp(-k * (t - t0)));
    const sig0 = 1 / (1 + Math.exp(-k * (-t0)));
    const sig1 = 1 / (1 + Math.exp(-k * (1 - t0)));
    sig = (sig - sig0) / (sig1 - sig0);

    const yDrift = arcHeight * Math.sin(Math.PI * t) + (Math.random() - 0.5) * 0.4;
    const x = distance * sig;
    const y = yDrift;
    const dx = x - prevX;
    const dy = y - prevY;
    prevX = x;
    prevY = y;
    const dt = dtBase * (Math.random() * 0.4 + 0.85);
    track.push({ dx, dy, dt: Math.floor(dt * 1000) });
  }
  return track;
}

async function solveOnce(captchaId, port) {
  let browser;
  try {
    const launchOptions = {
      headless: true,
      args: [
        '--disable-blink-features=AutomationControlled',
        '--no-sandbox',
        '--disable-infobars',
        '--disable-dev-shm-usage',
        '--disable-gpu'
      ]
    };

    const execPath = resolveChromiumExecutable();
    if (execPath) {
      launchOptions.executablePath = execPath;
    }

    browser = await chromium.launch(launchOptions);

    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      viewport: { width: 1280, height: 800 }
    });

    await context.addInitScript(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
      window.chrome = { runtime: {} };
    });

    const page = await context.newPage();
    page.on('console', msg => console.log('PAGE_LOG [' + msg.type() + ']:', msg.text()));
    page.on('response', resp => {
      if (resp.url().includes('verify')) {
        resp.text().then(t => console.log('VERIFY_BODY:', t.slice(0, 300))).catch(() => {});
      }
    });

    await page.goto('http://127.0.0.1:' + port + '/', { waitUntil: 'networkidle' });
    await page.evaluate((id) => window.initCaptcha(id), captchaId);

    await page.waitForFunction(() => window.gt4Ready === true, { timeout: 15000 });
    await page.evaluate(() => window.captchaObj.showCaptcha());

    const btn = await page.waitForSelector('.geetest_btn', { timeout: 8000 });
    await page.waitForSelector('.geetest_bg', { timeout: 8000 });
    await page.waitForSelector('.geetest_slice_bg', { timeout: 8000 });
    await new Promise(r => setTimeout(r, 1200));

    const btnBox = await btn.boundingBox();

    // Extract exact distance using in-page canvas matching
    const matchResult = await page.evaluate(async () => {
      function cleanUrl(bg) {
        if (!bg || bg === 'none') return '';
        let s = bg.trim();
        if (s.startsWith('url(')) s = s.slice(4);
        if (s.endsWith(')')) s = s.slice(0, -1);
        if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
          s = s.slice(1, -1);
        }
        return s;
      }
      const bgEl = document.querySelector('.geetest_bg');
      const sliceEl = document.querySelector('.geetest_slice_bg');
      const bgUrl = cleanUrl(window.getComputedStyle(bgEl).backgroundImage);
      const sliceUrl = cleanUrl(window.getComputedStyle(sliceEl).backgroundImage);
      const proxied = (u) => (u && !u.startsWith('data:'))
        ? ('/img?url=' + encodeURIComponent(u))
        : u;
      const bgRect = bgEl.getBoundingClientRect();
      const sliceRect = sliceEl.getBoundingClientRect();

      function loadImage(url) {
        return new Promise((resolve, reject) => {
          const img = new Image();
          img.crossOrigin = 'Anonymous';
          img.onload = () => resolve(img);
          img.onerror = reject;
          img.src = url;
        });
      }

      const bgImg = await loadImage(proxied(bgUrl));
      const sliceImg = await loadImage(proxied(sliceUrl));

      const bgCanvas = document.createElement('canvas');
      bgCanvas.width = bgImg.naturalWidth;
      bgCanvas.height = bgImg.naturalHeight;
      const bgCtx = bgCanvas.getContext('2d');
      bgCtx.drawImage(bgImg, 0, 0);
      const bgData = bgCtx.getImageData(0, 0, bgCanvas.width, bgCanvas.height).data;

      const sliceCanvas = document.createElement('canvas');
      sliceCanvas.width = sliceImg.naturalWidth;
      sliceCanvas.height = sliceImg.naturalHeight;
      const sliceCtx = sliceCanvas.getContext('2d');
      sliceCtx.drawImage(sliceImg, 0, 0);
      const sliceData = sliceCtx.getImageData(0, 0, sliceCanvas.width, sliceCanvas.height).data;

      const bgW = bgCanvas.width;
      const bgH = bgCanvas.height;
      const bgEdgeBin = new Uint8Array(bgW * bgH);
      for (let y = 1; y < bgH - 1; y++) {
        for (let x = 1; x < bgW - 1; x++) {
          const lLeft = bgData[((y) * bgW + (x - 1)) * 4] * 0.299 + bgData[((y) * bgW + (x - 1)) * 4 + 1] * 0.587 + bgData[((y) * bgW + (x - 1)) * 4 + 2] * 0.114;
          const lRight = bgData[((y) * bgW + (x + 1)) * 4] * 0.299 + bgData[((y) * bgW + (x + 1)) * 4 + 1] * 0.587 + bgData[((y) * bgW + (x + 1)) * 4 + 2] * 0.114;
          const lUp = bgData[((y - 1) * bgW + (x)) * 4] * 0.299 + bgData[((y - 1) * bgW + (x)) * 4 + 1] * 0.587 + bgData[((y - 1) * bgW + (x)) * 4 + 2] * 0.114;
          const lDown = bgData[((y + 1) * bgW + (x)) * 4] * 0.299 + bgData[((y + 1) * bgW + (x)) * 4 + 1] * 0.587 + bgData[((y + 1) * bgW + (x)) * 4 + 2] * 0.114;
          const gx = lRight - lLeft;
          const gy = lDown - lUp;
          if (Math.sqrt(gx * gx + gy * gy) > 28) {
            bgEdgeBin[y * bgW + x] = 1;
          }
        }
      }

      const sliceW = sliceCanvas.width;
      const sliceH = sliceCanvas.height;
      const edgePoints = [];
      for (let y = 0; y < sliceH; y++) {
        for (let x = 0; x < sliceW; x++) {
          const a = sliceData[(y * sliceW + x) * 4 + 3];
          if (a > 50) {
            let isBoundary = false;
            for (const [dx, dy] of [[-1,0],[1,0],[0,-1],[0,1]]) {
              const nx = x + dx, ny = y + dy;
              if (nx < 0 || nx >= sliceW || ny < 0 || ny >= sliceH || sliceData[(ny * sliceW + nx) * 4 + 3] <= 50) {
                isBoundary = true; break;
              }
            }
            if (isBoundary) {
              edgePoints.push({ x, y });
            }
          }
        }
      }

      const scale = bgRect.width / bgW;
      const exactY = Math.round((sliceRect.top - bgRect.top) / scale);

      let bestScore = 0;
      let bestX = 0;
      for (let dy = -3; dy <= 3; dy++) {
        const testY = exactY + dy;
        if (testY < 0 || testY + sliceH >= bgH) continue;
        for (let targetX = 35; targetX < bgW - sliceW + 10; targetX++) {
          let score = 0;
          for (let i = 0; i < edgePoints.length; i++) {
            const bx = targetX + edgePoints[i].x;
            const by = testY + edgePoints[i].y;
            if (bx >= 0 && bx < bgW && by >= 0 && by < bgH) {
              if (bgEdgeBin[by * bgW + bx] === 1) score++;
            }
          }
          if (score > bestScore) {
            bestScore = score;
            bestX = targetX;
          }
        }
      }

      return { rawDist: bestX, exactY, bestScore, scale, targetDist: bestX * scale };
    });

    console.log('Match result:', JSON.stringify(matchResult));

    // Button start position
    const startX = btnBox.x + btnBox.width / 2;
    const startY = btnBox.y + btnBox.height / 2;
    console.log('Starting slider drag from:', startX, startY);

    await btn.hover();
    await new Promise(r => setTimeout(r, 200));

    await page.mouse.down();
    await new Promise(r => setTimeout(r, 100));

    let currX = startX;
    let currY = startY;
    const btnTrack = await page.evaluate(() => {
      const s = document.querySelector('.geetest_slice_bg');
      const b = document.querySelector('.geetest_bg');
      const btn = document.querySelector('.geetest_btn');
      const slider = document.querySelector('.geetest_slider');
      return (b.clientWidth - s.clientWidth) / (slider.clientWidth - btn.clientWidth);
    });
    // Adjust targetDist so the slice reaches the exact target
    const btnDist = matchResult.targetDist - 0.5;
    console.log('Adjusted btnDist:', btnDist, 'from slice targetDist:', matchResult.targetDist);
    const track = generateHumanTrack(btnDist);

    for (const pt of track) {
      currX += pt.dx;
      currY += pt.dy;
      await page.mouse.move(currX, currY);
      await new Promise(r => setTimeout(r, pt.dt));
    }

    const actualSlicePos = await page.evaluate(() => {
      const s = document.querySelector('.geetest_slice_bg').getBoundingClientRect();
      const b = document.querySelector('.geetest_bg').getBoundingClientRect();
      return s.left - b.left;
    });
    console.log('ACTUAL_SLICE_POS:', actualSlicePos, 'TARGET_SLICE_POS:', matchResult.targetDist, 'DIFF:', actualSlicePos - matchResult.targetDist);
    await new Promise(r => setTimeout(r, 150));
    await page.mouse.up();
    console.log('Mouse up, polling for result...');

    for (let i = 0; i < 40; i++) {
      const res = await page.evaluate(() => window.gt4Result);
      if (res) {
        console.log('GOT_RESULT:', JSON.stringify(res));
        return res;
      }
      const err = await page.evaluate(() => window.gt4Error);
      if (err) {
        console.log('GOT_ERROR:', JSON.stringify(err));
        throw new Error('GeeTest returned error: ' + JSON.stringify(err));
      }
      await new Promise(r => setTimeout(r, 200));
    }
    return null;
  } finally {
    if (browser) await browser.close();
  }
}

function proxyImage(target, res, redirects = 0) {
  let parsed;
  try {
    parsed = new URL(target);
  } catch (e) {
    res.writeHead(400, { 'Content-Type': 'text/plain' });
    res.end('bad image url');
    return;
  }
  const client = parsed.protocol === 'https:' ? https : http;
  const req = client.get(parsed, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
      'Referer': 'https://www.geetest.com/'
    }
  }, (r) => {
    if (r.statusCode >= 300 && r.statusCode < 400 && r.headers.location && redirects < 3) {
      r.resume();
      proxyImage(new URL(r.headers.location, parsed).toString(), res, redirects + 1);
      return;
    }
    res.writeHead(r.statusCode || 200, {
      'Content-Type': r.headers['content-type'] || 'image/png',
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-store'
    });
    r.pipe(res);
  });
  req.on('error', (e) => {
    if (!res.headersSent) {
      res.writeHead(502, { 'Content-Type': 'text/plain' });
      res.end('image proxy error: ' + e.message);
    }
  });
  req.setTimeout(15000, () => req.destroy());
}

async function solveGeetestV4(captchaId, maxRetries = 3) {
  const localGt4 = fs.readFileSync(path.join(__dirname, 'assets', 'gt4.js'));
  const server = http.createServer((req, res) => {
    if (req.url === '/gt4.js') {
      res.writeHead(200, { 'Content-Type': 'application/javascript; charset=utf-8' });
      res.end(localGt4);
      return;
    }
    if (req.url.startsWith('/img?url=')) {
      let target = '';
      try {
        target = new URL(req.url, 'http://127.0.0.1').searchParams.get('url') || '';
      } catch (e) {}
      if (target) {
        proxyImage(target, res);
        return;
      }
    }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(HTML_CONTENT);
  });

  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  try {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      console.log('Attempt ' + attempt + '/' + maxRetries + '...');
      try {
        const res = await solveOnce(captchaId, port);
        if (res && res.lot_number) {
          return res;
        }
      } catch (e) {
        console.log('Attempt ' + attempt + ' failed:', e.message);
      }
      await new Promise(r => setTimeout(r, 1000));
    }
    throw new Error('Failed to solve after ' + maxRetries + ' attempts');
  } finally {
    server.close();
  }
}

(async () => {
  try {
    const captchaId = process.argv[2] || '3b02ad39bd099fd3a8336d9347a189ab';
    console.log('Solving GeeTest v4 for captcha_id:', captchaId);
    const res = await solveGeetestV4(captchaId);
    console.log('FINAL_RESULT:' + JSON.stringify(res));
  } catch (err) {
    console.error('SOLVER_ERROR:', err);
    process.exit(1);
  }
})();








