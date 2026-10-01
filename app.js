const { spawn, execSync } = require('child_process');

const pyCmd = process.platform === 'win32' ? 'python' : 'python3';

function setupEnvironment() {
    console.log("[Bothost Bridge] Checking Python environment & pip...");
    let hasPip = false;
    try {
        execSync(`${pyCmd} -m pip --version`, { stdio: 'ignore' });
        hasPip = true;
    } catch (e) {
        hasPip = false;
    }

    if (!hasPip) {
        console.log("[Bothost Bridge] pip is not installed. Downloading get-pip.py...");
        try {
            try {
                execSync(`curl -sSL https://bootstrap.pypa.io/get-pip.py -o get-pip.py`, { stdio: 'inherit' });
            } catch (errCurl) {
                execSync(`wget -q https://bootstrap.pypa.io/get-pip.py -O get-pip.py`, { stdio: 'inherit' });
            }
            console.log("[Bothost Bridge] Installing pip...");
            execSync(`${pyCmd} get-pip.py --no-warn-script-location`, { stdio: 'inherit' });
            console.log("[Bothost Bridge] pip installed successfully!");
        } catch (errPip) {
            console.log("[Bothost Bridge] Automatic pip installation note:", errPip.message);
        }
    }

    console.log("[Bothost Bridge] Installing Python requirements from requirements.txt...");
    try {
        execSync(`${pyCmd} -m pip install --no-cache-dir -r requirements.txt`, { stdio: 'inherit' });
        console.log("[Bothost Bridge] All Python dependencies installed successfully!");
    } catch (errReq) {
        console.log("[Bothost Bridge] Note on pip install:", errReq.message);
    }
}

try {
    setupEnvironment();
} catch (e) {
    console.log("[Bothost Bridge] Setup note:", e.message);
}

console.log("[Bothost Bridge] Starting Python application (app.py)...");

function startPython(cmd) {
    const child = spawn(cmd, ['app.py'], { stdio: 'inherit' });

    child.on('error', (err) => {
        console.error(`[Bothost Bridge] Failed to launch using '${cmd}':`, err.message);
        const altCmd = cmd === 'python3' ? 'python' : 'python3';
        console.log(`[Bothost Bridge] Attempting fallback to '${altCmd}'...`);
        const fallback = spawn(altCmd, ['app.py'], { stdio: 'inherit' });
        fallback.on('exit', (code) => process.exit(code || 0));
    });

    child.on('exit', (code) => {
        process.exit(code || 0);
    });
}

startPython(pyCmd);
