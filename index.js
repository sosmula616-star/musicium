const { spawn } = require('child_process');

console.log("Starting Python application (app.py)...");

const pyCmd = process.platform === 'win32' ? 'python' : 'python3';
const child = spawn(pyCmd, ['app.py'], { stdio: 'inherit' });

child.on('error', (err) => {
    console.error('Failed to launch python:', err);
    if (pyCmd === 'python3') {
        console.log('Retrying with python...');
        const fallback = spawn('python', ['app.py'], { stdio: 'inherit' });
        fallback.on('exit', (code) => process.exit(code || 0));
    }
});

child.on('exit', (code) => {
    process.exit(code || 0);
});
