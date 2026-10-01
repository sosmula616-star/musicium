const { spawn, execSync } = require('child_process');

const isWin = process.platform === 'win32';
const pyCmd = isWin ? 'python' : 'python3';

function checkAndInstallDeps() {
  console.log('[Runner] Checking Python environment...');
  try {
    execSync(`${pyCmd} --version`, { stdio: 'inherit' });
  } catch (err) {
    console.error('[Runner] Python executable not found:', err.message);
  }

  // Attempt installing requirements on startup if needed
  try {
    console.log('[Runner] Verifying Python requirements from requirements.txt...');
    execSync(`${pyCmd} -m pip install -q --no-cache-dir -r requirements.txt`, { stdio: 'inherit' });
    console.log('[Runner] Requirements verified.');
  } catch (err) {
    console.log('[Runner] Pip check notice:', err.message);
  }
}

try {
  checkAndInstallDeps();
} catch (e) {
  console.log('[Runner] Startup check notice:', e.message);
}

console.log('[Runner] Starting Python bot & web server (app.py)...');

function startProcess(command) {
  const child = spawn(command, ['app.py'], { stdio: 'inherit' });

  child.on('error', (err) => {
    console.error(`[Runner] Error launching with '${command}':`, err.message);
    const fallbackCmd = command === 'python3' ? 'python' : 'python3';
    console.log(`[Runner] Retrying with '${fallbackCmd}'...`);
    const fallback = spawn(fallbackCmd, ['app.py'], { stdio: 'inherit' });
    fallback.on('exit', (code) => process.exit(code || 0));
  });

  child.on('exit', (code) => {
    console.log(`[Runner] Application exited with code ${code}`);
    process.exit(code || 0);
  });
}

startProcess(pyCmd);
