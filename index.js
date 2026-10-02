const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');

console.log('==============================================');
console.log('  Discord Music Bot & Mini App Node.js Wrapper');
console.log('==============================================');

// Globally allow pip in externally-managed environments (PEP 668)
process.env.PIP_BREAK_SYSTEM_PACKAGES = '1';

// Write pip.conf to completely disable externally-managed checks
try {
  const homeDir = process.env.HOME || '/root';
  const pipDir = path.join(homeDir, '.config', 'pip');
  fs.mkdirSync(pipDir, { recursive: true });
  fs.writeFileSync(
    path.join(pipDir, 'pip.conf'),
    '[global]\nbreak-system-packages = true\n'
  );
} catch (e) {
  // ignore
}

function getPythonCommand() {
  const commands = ['python3', 'python'];
  for (const cmd of commands) {
    try {
      execSync(`${cmd} --version`, { stdio: 'ignore' });
      return cmd;
    } catch (e) {}
  }
  return null;
}

const basePyCmd = getPythonCommand();
if (!basePyCmd) {
  console.error('CRITICAL: Python is not installed in this container!');
  console.error('Please switch your server Egg / Image in bothost to "Python 3".');
  process.exit(1);
}

console.log(`System Python executable: ${basePyCmd}`);

// Virtual environment path
const isWindows = process.platform === 'win32';
const venvDir = path.join(__dirname, '.venv');
const venvPy = isWindows
  ? path.join(venvDir, 'Scripts', 'python.exe')
  : path.join(venvDir, 'bin', 'python');

function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    https.get(url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return downloadFile(res.headers.location, dest).then(resolve).catch(reject);
      }
      if (res.statusCode !== 200) {
        return reject(new Error(`Failed to download: status ${res.statusCode}`));
      }
      res.pipe(file);
      file.on('finish', () => file.close(resolve));
    }).on('error', (err) => {
      fs.unlink(dest, () => {});
      reject(err);
    });
  });
}

async function preparePython() {
  // Step 1: Try creating a virtual environment if not already present
  if (!fs.existsSync(venvPy)) {
    try {
      console.log('Attempting to create isolated virtual environment (.venv)...');
      execSync(`${basePyCmd} -m venv "${venvDir}"`, { stdio: 'inherit' });
      console.log('Virtual environment created successfully!');
    } catch (e) {
      console.log('Virtual environment creation not supported by host image. Proceeding with system python...');
    }
  }

  const activePy = fs.existsSync(venvPy) ? venvPy : basePyCmd;
  console.log(`Active Python engine: ${activePy}`);

  // Step 2: Check if pip works
  let pipWorking = false;
  try {
    execSync(`"${activePy}" -m pip --version`, { stdio: 'ignore' });
    pipWorking = true;
  } catch (e) {
    pipWorking = false;
  }

  // Step 3: If pip is missing, bootstrap via get-pip.py (skip ensurepip as ensurepip fails on Alpine 3.12)
  if (!pipWorking) {
    console.log('pip is not available. Downloading and installing pip via get-pip.py...');
    const getPipFile = path.join(__dirname, 'get-pip.py');
    try {
      await downloadFile('https://bootstrap.pypa.io/get-pip.py', getPipFile);
      console.log('get-pip.py downloaded. Running installer...');
      execSync(`"${activePy}" "${getPipFile}" --break-system-packages --no-warn-script-location`, {
        stdio: 'inherit',
        env: { ...process.env, PIP_BREAK_SYSTEM_PACKAGES: '1' }
      });
      console.log('pip installed successfully!');
    } catch (err) {
      console.error('get-pip install notice:', err.message);
    } finally {
      if (fs.existsSync(getPipFile)) {
        try { fs.unlinkSync(getPipFile); } catch (e) {}
      }
    }
  }

  // Step 4: Install dependencies from requirements.txt
  const reqFile = path.join(__dirname, 'requirements.txt');
  if (fs.existsSync(reqFile)) {
    console.log('Installing dependencies from requirements.txt...');
    try {
      execSync(`"${activePy}" -m pip install --break-system-packages --no-warn-script-location -r "${reqFile}"`, {
        stdio: 'inherit',
        env: { ...process.env, PIP_BREAK_SYSTEM_PACKAGES: '1' }
      });
      console.log('All Python dependencies installed successfully!');
    } catch (err) {
      console.warn('Pip install warning:', err.message);
    }
  }

  // Step 5: On Linux, attempt to install system ffmpeg and opus
  if (process.platform === 'linux') {
    try {
      execSync('apk add --no-cache ffmpeg opus opus-tools 2>/dev/null || apt-get install -y ffmpeg libopus0 2>/dev/null || true', { stdio: 'ignore' });
    } catch (_) {}
  }

  // Step 6: Ensure static_ffmpeg binary is downloaded
  try {
    execSync(`"${activePy}" -c "import static_ffmpeg.run; static_ffmpeg.run.check_or_set_filtered_ffmpeg_ffmpeg_download()" 2>/dev/null || true`, { stdio: 'ignore' });
  } catch (_) {}

  return activePy;
}

async function main() {
  const activePy = await preparePython();

  console.log('Launching main.py...');
  const bot = spawn(activePy, ['main.py'], {
    cwd: __dirname,
    stdio: 'inherit',
    env: { ...process.env, PIP_BREAK_SYSTEM_PACKAGES: '1' },
  });

  bot.on('close', (code) => {
    console.log(`Bot process exited with code ${code}`);
    process.exit(code || 0);
  });

  bot.on('error', (err) => {
    console.error('Failed to start python process:', err);
    process.exit(1);
  });
}

main();
