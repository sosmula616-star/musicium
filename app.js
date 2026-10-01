const { spawn, execSync } = require('child_process');
const fs = require('fs');
const https = require('https');
const path = require('path');

const isWin = process.platform === 'win32';
const pyCmd = isWin ? 'python' : 'python3';

function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    const get = (targetUrl) => {
      https.get(targetUrl, (response) => {
        if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
          get(response.headers.location);
          return;
        }
        if (response.statusCode !== 200) {
          file.close();
          fs.unlink(dest, () => {});
          reject(new Error(`Server returned status code ${response.statusCode}`));
          return;
        }
        response.pipe(file);
        file.on('finish', () => {
          file.close(resolve);
        });
      }).on('error', (err) => {
        file.close();
        fs.unlink(dest, () => {});
        reject(err);
      });
    };
    get(url);
  });
}

async function ensurePip() {
  console.log('[Runner] Checking if pip is available...');
  try {
    execSync(`${pyCmd} -m pip --version`, { stdio: 'ignore' });
    console.log('[Runner] pip is already installed.');
    return true;
  } catch (e) {
    console.log('[Runner] pip not found. Attempting to install pip...');
  }

  // 1. Try python3 -m ensurepip
  try {
    console.log('[Runner] Trying ensurepip...');
    execSync(`${pyCmd} -m ensurepip --default-pip --break-system-packages`, { stdio: 'inherit' });
    return true;
  } catch (errEnsure) {
    try {
      execSync(`${pyCmd} -m ensurepip --default-pip`, { stdio: 'inherit' });
      return true;
    } catch (e2) {
      console.log('[Runner] ensurepip unavailable, downloading get-pip.py...');
    }
  }

  // 2. Download get-pip.py
  const getPipPath = path.join(__dirname, 'get-pip.py');
  try {
    console.log('[Runner] Downloading get-pip.py...');
    try {
      execSync(`curl -sSL https://bootstrap.pypa.io/get-pip.py -o "${getPipPath}"`, { stdio: 'inherit' });
    } catch (errCurl) {
      try {
        execSync(`wget -q https://bootstrap.pypa.io/get-pip.py -O "${getPipPath}"`, { stdio: 'inherit' });
      } catch (errWget) {
        await downloadFile('https://bootstrap.pypa.io/get-pip.py', getPipPath);
      }
    }

    console.log('[Runner] Running get-pip.py...');
    try {
      execSync(`${pyCmd} "${getPipPath}" --break-system-packages --no-warn-script-location`, { stdio: 'inherit' });
    } catch (errRun1) {
      execSync(`${pyCmd} "${getPipPath}" --no-warn-script-location`, { stdio: 'inherit' });
    }
    console.log('[Runner] pip installed successfully via get-pip.py!');
    return true;
  } catch (errPip) {
    console.error('[Runner] Failed to install pip:', errPip.message);
    return false;
  }
}

async function setupAndStart() {
  console.log(`[Runner] Python runtime: ${pyCmd}`);
  try {
    execSync(`${pyCmd} --version`, { stdio: 'inherit' });
  } catch (err) {
    console.error(`[Runner] ${pyCmd} is not available:`, err.message);
  }

  const hasPip = await ensurePip();

  if (hasPip) {
    console.log('[Runner] Installing packages from requirements.txt...');
    try {
      execSync(`${pyCmd} -m pip install --break-system-packages --no-cache-dir -r requirements.txt`, { stdio: 'inherit' });
      console.log('[Runner] All Python requirements installed.');
    } catch (errReq) {
      try {
        execSync(`${pyCmd} -m pip install --no-cache-dir -r requirements.txt`, { stdio: 'inherit' });
        console.log('[Runner] Python requirements installed without --break-system-packages.');
      } catch (errReqFallback) {
        console.error('[Runner] Warning during pip install:', errReqFallback.message);
      }
    }
  }

  console.log('[Runner] Starting Python bot & web server (app.py)...');
  startPythonProcess(pyCmd);
}

function startPythonProcess(command) {
  const child = spawn(command, ['app.py'], { stdio: 'inherit' });

  child.on('error', (err) => {
    console.error(`[Runner] Failed to launch with '${command}':`, err.message);
    const fallbackCmd = command === 'python3' ? 'python' : 'python3';
    console.log(`[Runner] Attempting fallback to '${fallbackCmd}'...`);
    const fallback = spawn(fallbackCmd, ['app.py'], { stdio: 'inherit' });
    fallback.on('exit', (code) => process.exit(code || 0));
  });

  child.on('exit', (code) => {
    console.log(`[Runner] Application exited with code ${code}`);
    process.exit(code || 0);
  });
}

setupAndStart().catch((err) => {
  console.error('[Runner] Fatal startup error:', err);
  process.exit(1);
});
