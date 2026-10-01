const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const isWin = process.platform === 'win32';
const venvDir = path.join(__dirname, '.venv');
const venvPy = isWin
  ? path.join(venvDir, 'Scripts', 'python.exe')
  : path.join(venvDir, 'bin', 'python');
const venvPip = isWin
  ? path.join(venvDir, 'Scripts', 'pip.exe')
  : path.join(venvDir, 'bin', 'pip');

const sysPy = isWin ? 'python' : 'python3';

function runQuiet(cmd) {
  try {
    execSync(cmd, { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

function runInherit(cmd) {
  try {
    execSync(cmd, { stdio: 'inherit' });
    return true;
  } catch {
    return false;
  }
}

function prepareEnvironment() {
  console.log('[Runner] Preparing Python environment...');

  if (fs.existsSync(venvPy)) {
    console.log('[Runner] Found existing virtual environment (.venv).');
    return { py: venvPy, pip: venvPip };
  }

  console.log('[Runner] Creating virtual environment (.venv)...');
  const created = runQuiet(`${sysPy} -m venv "${venvDir}"`);
  if (created && fs.existsSync(venvPy)) {
    console.log('[Runner] Virtual environment created successfully.');
    return { py: venvPy, pip: venvPip };
  }

  // Alpine Linux check
  if (!isWin && runQuiet('which apk')) {
    console.log('[Runner] Alpine detected. Installing dependencies via apk...');
    runInherit('apk add --no-cache py3-pip py3-virtualenv python3-dev build-base ffmpeg opus-dev libffi-dev');
    if (runQuiet(`${sysPy} -m venv "${venvDir}"`) && fs.existsSync(venvPy)) {
      console.log('[Runner] Virtual environment created after apk install.');
      return { py: venvPy, pip: venvPip };
    }
  }

  if (runQuiet(`${sysPy} -m pip --version`)) {
    console.log('[Runner] Fallback: Using system Python.');
    return { py: sysPy, pip: `${sysPy} -m pip`, isSystem: true };
  }

  return { py: sysPy, pip: `${sysPy} -m pip`, isSystem: true };
}

function main() {
  const env = prepareEnvironment();
  const reqPath = path.join(__dirname, 'requirements.txt');

  if (fs.existsSync(reqPath)) {
    console.log('[Runner] Installing dependencies from requirements.txt...');
    const extraFlag = env.isSystem ? ' --break-system-packages' : '';
    const cmd = `${env.pip} install --no-cache-dir${extraFlag} -r "${reqPath}"`;
    const ok = runInherit(cmd);
    if (!ok) {
      runInherit(`${env.pip} install${extraFlag} -r "${reqPath}"`);
    }
  }

  console.log(`[Runner] Starting Discord Bot with ${env.py}...`);
  const child = spawn(env.py, ['main.py'], {
    stdio: 'inherit',
    cwd: __dirname,
  });

  child.on('error', (err) => {
    console.error('[Runner] Error running bot:', err);
    process.exit(1);
  });

  child.on('exit', (code) => {
    console.log(`[Runner] Bot process exited with code ${code}`);
    process.exit(code || 0);
  });
}

main();
