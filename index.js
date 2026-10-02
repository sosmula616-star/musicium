const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');

console.log('==============================================');
console.log('  Discord Music Bot & Mini App Node.js Wrapper');
console.log('==============================================');

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

const pyCmd = getPythonCommand();
if (!pyCmd) {
  console.error('CRITICAL: Python is not installed in this container!');
  console.error('Please switch your server Egg / Image in bothost to "Python 3".');
  process.exit(1);
}

console.log(`Using Python executable: ${pyCmd}`);

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
    execSync(`${pyCmd} -m pip --version`, { stdio: 'ignore' });
    pipAvailable = true;
  } catch (e) {
    pipAvailable = false;
  }

  if (!pipAvailable) {
    console.log('pip is not present. Bootstrapping pip automatically...');
    let bootstrapSuccess = false;

    // Try ensurepip
    try {
      execSync(`${pyCmd} -m ensurepip --user`, { stdio: 'inherit' });
      bootstrapSuccess = true;
    } catch (e) {
      console.log('ensurepip not available, downloading get-pip.py...');
    }

    if (!bootstrapSuccess) {
      try {
        const getPipPath = path.join(__dirname, 'get-pip.py');
        await downloadFile('https://bootstrap.pypa.io/get-pip.py', getPipPath);
        execSync(`${pyCmd} "${getPipPath}" --user --no-warn-script-location`, { stdio: 'inherit' });
        if (fs.existsSync(getPipPath)) {
          fs.unlinkSync(getPipPath);
        }
        bootstrapSuccess = true;
        console.log('pip bootstrapped successfully!');
      } catch (err) {
        console.error('Failed to bootstrap pip automatically:', err.message);
      }
    }
  }

  // Install requirements
  const reqPath = path.join(__dirname, 'requirements.txt');
  if (fs.existsSync(reqPath)) {
    console.log('Checking and installing Python dependencies from requirements.txt...');
    try {
      execSync(`${pyCmd} -m pip install --user --no-warn-script-location -r "${reqPath}"`, { stdio: 'inherit' });
      console.log('Dependencies installed successfully!');
    } catch (err) {
      console.warn('Pip install warning:', err.message);
    }
  }
}

async function start() {
  await preparePythonEnvironment();

  console.log('Launching main.py...');
  const bot = spawn(pyCmd, ['main.py'], {
    cwd: __dirname,
    stdio: 'inherit',
    env: process.env,
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
