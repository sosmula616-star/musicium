const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

console.log('==============================================');
console.log('  Discord Music Bot & Mini App Node.js Wrapper');
console.log('==============================================');

// Detect Python executable
function getPythonCommand() {
  const commands = ['python3', 'python'];
  for (const cmd of commands) {
    try {
      execSync(`${cmd} --version`, { stdio: 'ignore' });
      return cmd;
    } catch (e) {
      // not available
    }
  }
  return null;
}

const pyCmd = getPythonCommand();
if (!pyCmd) {
  console.error('CRITICAL: Python is not installed in this container!');
  console.error('Please switch your server Egg / Image in bothost to "Python 3" instead of "Node.js".');
  process.exit(1);
}

console.log(`Using Python executable: ${pyCmd}`);

// Install requirements if requirements.txt exists
if (fs.existsSync(path.join(__dirname, 'requirements.txt'))) {
  console.log('Checking and installing Python dependencies...');
  try {
    execSync(`${pyCmd} -m pip install -r requirements.txt`, { stdio: 'inherit' });
  } catch (err) {
    console.warn('Pip install encountered an issue, proceeding to start bot anyway...');
  }
}

// Spawn Python main.py
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
