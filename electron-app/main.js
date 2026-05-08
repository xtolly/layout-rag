const { app, BrowserWindow, ipcMain, protocol, net } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const fs = require('fs')

// ============================================================
//  配置中心
// ============================================================
const CLOUD_BACKEND_URL = 'http://localhost:8000'; // 你的云端服务器地址
// ============================================================

const MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
}

// 注册自定义协议（必须在 app ready 之前调用）
protocol.registerSchemesAsPrivileged([
    { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true } }
]);

let externalData = null;
let outputFilePath = null;
let wasSubmitted = false; // 标记是否成功提交方案

function createWindow() {
    // 创建主窗口
    const mainWindow = new BrowserWindow({
        width: 1440,
        height: 900,
        title: "Layout RAG Client",
        show: true,
        autoHideMenuBar: true,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true,
        }
    });

    mainWindow.setMenuBarVisibility(false);

    // 检查命令行参数：第一个 .json 为输入，第二个 .json 为输出
    const args = process.argv.slice(app.isPackaged ? 1 : 2);
    let targetUrl = `app://local/configurator.html`;

    const jsonFiles = args.filter(arg => arg && arg.toLowerCase().endsWith('.json'));

    // 处理输入路径
    if (jsonFiles.length >= 1) {
        const inputPath = path.isAbsolute(jsonFiles[0]) ? jsonFiles[0] : path.join(process.cwd(), jsonFiles[0]);
        if (fs.existsSync(inputPath)) {
            try {
                const content = fs.readFileSync(inputPath, 'utf8');
                externalData = JSON.parse(content);
                console.log(`[Input Data] Loaded from: ${inputPath}`);
                targetUrl = `app://local/layout_workbench.html?data_key=${Date.now()}`;
            } catch (e) {
                console.error(`[Input Data] Error reading file: ${inputPath}`, e);
            }
        }
    }

    // 处理输出路径
    if (jsonFiles.length >= 2) {
        outputFilePath = path.isAbsolute(jsonFiles[1]) ? jsonFiles[1] : path.join(process.cwd(), jsonFiles[1]);
        console.log(`[Output Path] Set to: ${outputFilePath}`);
    }

    // 直接加载目标页面
    mainWindow.loadURL(targetUrl);
}

function registerIpcHandlers() {
    // 接收前端提交的最终布局数据并保存到文件
    ipcMain.handle('submit-layout-result', async (event, payload) => {
        try {
            if (outputFilePath) {
                const jsonStr = JSON.stringify(payload, null, 2);
                fs.writeFileSync(outputFilePath, jsonStr, 'utf8');
                console.log(`[Success] Result saved to: ${outputFilePath}`);
                wasSubmitted = true;
                app.exit(0); // 成功提交：返回 0
            } else {
                console.warn('[Warning] No output path provided');
                wasSubmitted = true;
                app.exit(0);
            }
        } catch (err) {
            console.error(`[Error] Failed to save result: ${err.message}`);
            app.exit(1); // 异常：返回 1
        }
        return true;
    });

    ipcMain.on('exit-app', (event, code) => {
        console.log(`[Exit] App exiting with code: ${code}`);
        app.exit(code || 0);
    });

    ipcMain.handle('run-external-exe', async (event, args) => {
        return new Promise((resolve, reject) => {
            let exeDir = app.isPackaged
                ? path.join(process.resourcesPath, 'external_tools')
                : path.join(__dirname, 'external_tools');

            if (!fs.existsSync(exeDir)) return reject(new Error('找不到 external_tools 目录'));

            const files = fs.readdirSync(exeDir);
            const exeFile = files.find(f => f.endsWith('.exe'));
            if (!exeFile) return reject(new Error('未找到 .exe 文件'));

            const child = spawn(path.join(exeDir, exeFile), []);
            let resultData = '', errorData = '';

            child.stdin.write(JSON.stringify(args) + '\n');
            child.stdin.end();

            child.stdout.on('data', d => { resultData += d.toString(); });
            child.stderr.on('data', d => { errorData += d.toString(); });

            child.on('close', code => {
                if (code === 0) resolve(resultData.trim());
                else reject(new Error(`Exit ${code}: ${errorData}`));
            });
        });
    });
}

app.whenReady().then(async () => {
    const staticDir = path.join(__dirname, 'static');

    // 处理自定义协议请求
    protocol.handle('app', async (request) => {
        const url = new URL(request.url);
        let urlPath = url.pathname;

        // 1. 处理 API 代理：转发到云端
        if (urlPath.startsWith('/api')) {
            const fullTargetUrl = `${CLOUD_BACKEND_URL}${urlPath}${url.search}`;
            console.log(`[Protocol Proxy] ${request.method} ${urlPath} -> ${fullTargetUrl}`);

            try {
                return await net.fetch(fullTargetUrl, {
                    method: request.method,
                    headers: request.headers,
                    body: request.body,
                    duplex: 'half' // 对于流式 body 必须
                });
            } catch (err) {
                console.error('[Proxy Error]', err);
                return new Response('Cloud server unreachable', { status: 502 });
            }
        }

        // 2. 处理外部传入的临时数据
        if (urlPath === '/external-data') {
            return new Response(JSON.stringify(externalData), {
                headers: { 'Content-Type': 'application/json; charset=utf-8' }
            });
        }

        // 3. 映射静态资源路径
        if (urlPath === '/' || urlPath === '') urlPath = '/configurator.html';
        if (urlPath === '/layout') urlPath = '/layout_workbench.html';
        if (urlPath.startsWith('/static/')) urlPath = urlPath.slice('/static'.length);

        const filePath = path.join(staticDir, urlPath);

        try {
            const data = await fs.promises.readFile(filePath);
            const ext = path.extname(filePath).toLowerCase();
            return new Response(data, {
                status: 200,
                headers: { 'Content-Type': MIME[ext] || 'application/octet-stream' }
            });
        } catch (err) {
            console.error(`[File Error] ${urlPath} not found at ${filePath}`);
            return new Response(`Not found: ${urlPath}`, { status: 404 });
        }
    });

    registerIpcHandlers();
    createWindow();

    app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        if (!wasSubmitted) {
            console.log('[Exit] User closed the window manually (Cancel).');
            app.exit(2); // 用户手动关闭：返回 2
        } else {
            app.quit();
        }
    }
});

