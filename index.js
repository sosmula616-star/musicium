const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');

console.log('==============================================');
console.log('  Discord Music Bot & Mini App Node.js Wrapper');
console.log('==============================================');

// Allow installing packages in externally managed environments (Alpine/Debian PEP 668)
process.env.PIP_BREAK_SYSTEM_PACKAGES = '1';

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

// Try setting up a virtual environment in .venv
const isWindows = process.platform === 'win32';
const venvDir = path.join(__dirname, '.venv');
const venvPy = isWindows
  ? path.join(venvDir, 'Scripts', 'python.exe')
  : path.join(venvDir, 'bin', 'python');

if (!fs.existsSync(venvPy)) {
  try {
    console.log('Creating virtual environment (.venv)...');
    execSync(`${basePyCmd} -m venv "${venvDir}"`, { stdio: 'inherit' });
    console.log('Virtual environment (.venv) created successfully!');
  } catch (e) {
    console.log('Virtual environment not supported by base image, using direct Python with break-system-packages.');
  }
}

const activePy = fs.existsSync(venvPy) ? venvPy : basePyCmd;
console.log(`Active Python: ${activePy}`);

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

async function preparePythonEnvironment() {
  let pipAvailable = false;
  try {
    execSync(`"${activePy}" -m pip --version`, { stdio: 'ignore' });
    pipAvailable = true;
  } catch (e) {
    pipAvailable = false;
  }

  if (!pipAvailable) {
    console.log('pip is not present. Bootstrapping pip...');
    let bootstrapSuccess = false;

    // Try ensurepip with break-system-packages
    try {
      execSync(`"${activePy}" -m ensurepip --default-pip --break-system-packages`, {
        stdio: 'inherit',
        env: { ...process.env, PIP_BREAK_SYSTEM_PACKAGES: '1' }
      });
      bootstrapSuccess = true;
    } catch (e) {
      console.log('ensurepip not available, downloading get-pip.py...');
    }

    if (!bootstrapSuccess) {
      try {
        const getPipPath = path.join(__dirname, 'get-pip.py');
        await downloadFile('https://bootstrap.pypa.io/get-pip.py', getPipPath);
        execSync(`"${activePy}" "${getPipPath}" --break-system-packages --no-warn-script-location`, {
          stdio: 'inherit',
          env: { ...process.env, PIP_BREAK_SYSTEM_PACKAGES: '1' }
        });
        if (fs.existsSync(getPipPath)) {
          fs.unlinkSync(getPipPath);
        }
        bootstrapSuccess = true;
        console.log('pip bootstrapped successfully!');
      } catch (err) {
        console.error('Error downloading/running get-pip.py:', err.message);
      }
    }
  }

  // Install requirements from requirements.txt
  const reqPath = path.join(__dirname, 'requirements.txt');
  if (fs.existsSync(reqPath)) {
    console.log('Installing dependencies from requirements.txt...');
    try {
      execSync(`"${activePy}" -m pip install --break-system-packages --no-warn-script-location -r "${reqPath}"`, {
        stdio: 'inherit',
        env: { ...process.env, PIP_BREAK_SYSTEM_PACKAGES: '1' }
      });
      console.log('Dependencies installed successfully!');
    } catch (err) {
      console.warn('Pip install notice:', err.message);
    }
  }
}

async function start() {
  await preparePythonEnvironment();

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

start();
