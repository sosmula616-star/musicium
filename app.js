const { spawn, execSync } = require('child_process');
const fs = require('fs');
const https = require('https');
const path = require('path');

const isWin = process.platform === 'win32';
const venvDir = path.join(__dirname, '.venv');
const venvPython = isWin
  ? path.join(venvDir, 'Scripts', 'python.exe')
  : path.join(venvDir, 'bin', 'python');
const venvPip = isWin
  ? path.join(venvDir, 'Scripts', 'pip.exe')
  : path.join(venvDir, 'bin', 'pip');

const systemPy = isWin ? 'python' : 'python3';

function runQuiet(cmd) {
  try {
    execSync(cmd, { stdio: 'ignore' });
    return true;
  } catch (e) {
    return false;
  }
}

function runInherit(cmd) {
  try {
    execSync(cmd, { stdio: 'inherit' });
    return true;
  } catch (e) {
    return false;
  }
}

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
          reject(new Error(`HTTP ${response.statusCode}`));
          return;
        }
        response.pipe(file);
        file.on('finish', () => file.close(resolve));
      }).on('error', (err) => {
        file.close();
        fs.unlink(dest, () => {});
        reject(err);
      });
    };
    get(url);
  });
}

async function preparePythonEnvironment() {
  console.log('[Runner] Preparing Python environment...');

  // 1. If virtual environment already exists and works, use it directly!
  if (fs.existsSync(venvPython)) {
    console.log('[Runner] Existing virtual environment found (.venv).');
    return { py: venvPython, pip: venvPip };
  }

  // 2. Try creating a virtual environment (.venv)
  console.log('[Runner] Attempting to create virtual environment (.venv)...');
  const venvCreated = runQuiet(`${systemPy} -m venv "${venvDir}"`);
  if (venvCreated && fs.existsSync(venvPython)) {
    console.log('[Runner] Virtual environment created successfully!');
    return { py: venvPython, pip: venvPip };
  }

  // 3. If on Alpine Linux and venv failed, try installing py3-pip / py3-virtualenv via apk if possible
  if (!isWin && runQuiet('which apk')) {
    console.log('[Runner] Alpine Linux detected. Attempting to install py3-pip & py3-virtualenv...');
    runInherit('apk add --no-cache py3-pip py3-virtualenv python3-dev build-base ffmpeg');
    // Retry venv
    if (runQuiet(`${systemPy} -m venv "${venvDir}"`) && fs.existsSync(venvPython)) {
      console.log('[Runner] Virtual environment created after apk package installation!');
      return { py: venvPython, pip: venvPip };
    }
  }

  // 4. Fallback to system Python if pip is available
  if (runQuiet(`${systemPy} -m pip --version`)) {
    console.log('[Runner] Using system Python with pip.');
    return { py: systemPy, pip: `${systemPy} -m pip`, isSystem: true };
  }

  // 5. Try downloading and running get-pip.py as last resort
  const getPipFile = path.join(__dirname, 'get-pip.py');
  console.log('[Runner] Downloading get-pip.py...');
  try {
    await downloadFile('https://bootstrap.pypa.io/get-pip.py', getPipFile);
    console.log('[Runner] Installing pip with get-pip.py...');
    runInherit(`${systemPy} "${getPipFile}" --break-system-packages --no-warn-script-location`);
    if (runQuiet(`${systemPy} -m pip --version`)) {
      return { py: systemPy, pip: `${systemPy} -m pip`, isSystem: true };
    }
  } catch (err) {
    console.warn('[Runner] get-pip.py fallback note:', err.message);
  }

  console.warn('[Runner] Virtual environment could not be created; attempting system Python fallback.');
  return { py: systemPy, pip: `${systemPy} -m pip`, isSystem: true };
}

async function start() {
  const env = await preparePythonEnvironment();
  console.log(`[Runner] Python executable: ${env.py}`);

  // Check requirements
  const reqFile = path.join(__dirname, 'requirements.txt');
  if (fs.existsSync(reqFile)) {
    console.log('[Runner] Installing / verifying dependencies from requirements.txt...');
    const extraFlag = env.isSystem ? ' --break-system-packages' : '';
    const pipCmd = typeof env.pip === 'string' && env.pip.includes(' ')
      ? `${env.pip} install --no-cache-dir${extraFlag} -r "${reqFile}"`
      : `"${env.pip}" install --no-cache-dir${extraFlag} -r "${reqFile}"`;

    const success = runInherit(pipCmd);
    if (!success) {
      console.warn('[Runner] Direct pip install failed, retrying without cache flags...');
      runInherit(`${env.pip} install${extraFlag} -r "${reqFile}"`);
    }
  }

  console.log(`[Runner] Launching app.py with ${env.py}...`);
  const child = spawn(env.py, ['app.py'], {
    stdio: 'inherit',
    cwd: __dirname,
  });

  child.on('error', (err) => {
    console.error('[Runner] Process launch error:', err);
    process.exit(1);
  });

  child.on('exit', (code) => {
    console.log(`[Runner] Process finished with exit code ${code}`);
    process.exit(code || 0);
  });
}

start().catch((err) => {
  console.error('[Runner] Fatal error:', err);
  process.exit(1);
});
