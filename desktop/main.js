const { app, BrowserWindow } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const APP_TITLE = "RFP BidOS";
const OLLAMA_BASE_URL = "http://127.0.0.1:11434";
const OLLAMA_MODEL = "qwen3:8b";
const BACKEND_URL = "http://127.0.0.1:8000";
const FRONTEND_URL = "http://localhost:5173";

const desktopDir = __dirname;
const rootDir = path.resolve(desktopDir, "..");
const backendDir = path.join(rootDir, "backend");
const frontendDir = path.join(rootDir, "frontend");

const started = {
  ollama: null,
  backend: null,
  frontend: null,
};

let mainWindow = null;
let shuttingDown = false;

function iconPath() {
  const candidates = [
    path.join(desktopDir, "assets", process.platform === "darwin" ? "icon.icns" : ""),
    path.join(desktopDir, "assets", process.platform === "win32" ? "icon.ico" : ""),
    path.join(desktopDir, "assets", "icon.png"),
  ].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    title: APP_TITLE,
    icon: iconPath(),
    webPreferences: {
      preload: path.join(desktopDir, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.setTitle(APP_TITLE);
  showStatus("Starting RFP BidOS", "Checking local services...");
}

function html(title, message, detail = "") {
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>${escapeHtml(APP_TITLE)}</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f9;
      color: #172033;
    }
    main {
      width: min(560px, calc(100vw - 48px));
      border: 1px solid #d8dee8;
      border-radius: 8px;
      background: #ffffff;
      padding: 28px;
      box-shadow: 0 12px 40px rgba(20, 32, 50, 0.10);
    }
    h1 { margin: 0 0 10px; font-size: 24px; letter-spacing: 0; }
    p { margin: 8px 0; line-height: 1.45; }
    pre {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      padding: 12px;
      border-radius: 6px;
      background: #eef2f7;
      color: #202a3a;
    }
  </style>
</head>
<body>
  <main>
    <h1>${escapeHtml(title)}</h1>
    <p>${escapeHtml(message)}</p>
    ${detail ? `<pre>${escapeHtml(detail)}</pre>` : ""}
  </main>
</body>
</html>`;
}

function showStatus(title, message, detail = "") {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html(title, message, detail))}`);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function commandExists(command) {
  const checker = process.platform === "win32" ? "where" : "command";
  const args = process.platform === "win32" ? [command] : ["-v", command];
  const options = process.platform === "win32" ? {} : { shell: true };
  return spawnSync(checker, args, options).status === 0;
}

function pythonPath() {
  return process.platform === "win32"
    ? path.join(backendDir, ".venv", "Scripts", "python.exe")
    : path.join(backendDir, ".venv", "bin", "python");
}

function checkPrerequisites() {
  const missing = [];
  if (!fs.existsSync(path.join(backendDir, ".venv"))) {
    missing.push("backend/.venv is missing. Create it with Python 3.12+ and install backend requirements.");
  }
  if (!fs.existsSync(pythonPath())) {
    missing.push(`Python venv executable is missing: ${path.relative(rootDir, pythonPath())}`);
  }
  if (!fs.existsSync(path.join(frontendDir, "node_modules"))) {
    missing.push("frontend/node_modules is missing. Run: cd frontend && npm install");
  }
  if (!commandExists(process.platform === "win32" ? "npm.cmd" : "npm")) {
    missing.push("npm is not installed or not on PATH.");
  }
  if (!commandExists("ollama")) {
    missing.push("Ollama is not installed or not on PATH.");
  }
  if (missing.length) {
    throw new Error(`${missing.join("\n")}\n\nRequired setup:\ncd backend\npython -m pip install -r requirements.txt\npython -m app.cli init-db\npython -m app.cli seed-demo\npython -m app.cli seed-sources\n\ncd ../frontend\nnpm install\n\nollama pull ${OLLAMA_MODEL}`);
  }
}

function getJson(url, timeoutMs = 3000) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`${url} returned HTTP ${res.statusCode}`));
          return;
        }
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });
    req.on("timeout", () => {
      req.destroy(new Error(`${url} timed out`));
    });
    req.on("error", reject);
  });
}

function waitForUrl(url, timeoutMs, label) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(url, { timeout: 1500 }, (res) => {
        res.resume();
        if (res.statusCode >= 200 && res.statusCode < 500) {
          resolve();
          return;
        }
        retry();
      });
      req.on("timeout", () => req.destroy(new Error("timeout")));
      req.on("error", retry);
    };
    const retry = () => {
      if (Date.now() - start > timeoutMs) {
        reject(new Error(`${label} did not become ready at ${url}`));
        return;
      }
      setTimeout(attempt, 1000);
    };
    attempt();
  });
}

async function ensureOllama() {
  showStatus("Starting RFP BidOS", "Checking Ollama...");
  let tags = await tryOllamaTags();
  if (!tags) {
    showStatus("Starting RFP BidOS", "Ollama is not reachable. Starting ollama serve...");
    started.ollama = spawn("ollama", ["serve"], {
      cwd: rootDir,
      env: process.env,
      stdio: "pipe",
      windowsHide: true,
    });
    attachProcessLogging("Ollama", started.ollama);
    await waitForUrl(`${OLLAMA_BASE_URL}/api/tags`, 30000, "Ollama");
    tags = await tryOllamaTags();
  }

  const names = Array.isArray(tags?.models)
    ? tags.models.map((model) => model.name || model.model).filter(Boolean)
    : [];
  if (!names.includes(OLLAMA_MODEL)) {
    throw new Error(`Ollama is running, but ${OLLAMA_MODEL} is not installed. Run: ollama pull ${OLLAMA_MODEL}`);
  }
}

async function tryOllamaTags() {
  try {
    return await getJson(`${OLLAMA_BASE_URL}/api/tags`, 3000);
  } catch {
    return null;
  }
}

async function ensureBackend() {
  showStatus("Starting RFP BidOS", "Checking backend...");
  if (await urlReady(`${BACKEND_URL}/health`)) return;

  showStatus("Starting RFP BidOS", "Starting FastAPI backend...");
  if (process.platform === "win32") {
    started.backend = spawn("cmd.exe", ["/d", "/s", "/c", [
      ".venv\\Scripts\\activate.bat",
      `set OLLAMA_BASE_URL=${OLLAMA_BASE_URL}`,
      `set OLLAMA_MODEL=${OLLAMA_MODEL}`,
      "uvicorn app.main:app --host 127.0.0.1 --port 8000",
    ].join(" && ")], {
      cwd: backendDir,
      env: process.env,
      stdio: "pipe",
      windowsHide: true,
    });
  } else {
    started.backend = spawn("bash", ["-lc", [
      "source .venv/bin/activate",
      `export OLLAMA_BASE_URL=${OLLAMA_BASE_URL}`,
      `export OLLAMA_MODEL=${OLLAMA_MODEL}`,
      "uvicorn app.main:app --host 127.0.0.1 --port 8000",
    ].join(" && ")], {
      cwd: backendDir,
      env: process.env,
      stdio: "pipe",
    });
  }
  attachProcessLogging("Backend", started.backend);
  await waitForUrl(`${BACKEND_URL}/health`, 30000, "Backend");
}

async function ensureFrontend() {
  showStatus("Starting RFP BidOS", "Checking frontend...");
  if (await urlReady(FRONTEND_URL)) return;

  showStatus("Starting RFP BidOS", "Starting Vite frontend...");
  const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
  started.frontend = spawn(npmCommand, ["run", "dev"], {
    cwd: frontendDir,
    env: {
      ...process.env,
      VITE_API_BASE_URL: BACKEND_URL,
    },
    stdio: "pipe",
    windowsHide: true,
  });
  attachProcessLogging("Frontend", started.frontend);
  await waitForUrl(FRONTEND_URL, 30000, "Frontend");
}

async function urlReady(url) {
  try {
    await waitForUrl(url, 1000, url);
    return true;
  } catch {
    return false;
  }
}

function attachProcessLogging(label, child) {
  let output = "";
  const append = (chunk) => {
    output = `${output}${chunk.toString()}`.slice(-8000);
  };
  child.stdout?.on("data", append);
  child.stderr?.on("data", append);
  child.on("exit", (code, signal) => {
    if (!shuttingDown && code !== 0 && code !== null) {
      showStatus(`${label} stopped`, `${label} exited before the launcher closed.`, `Exit code: ${code}\nSignal: ${signal || "-"}\n\n${output}`);
    }
  });
  child.on("error", (error) => {
    if (!shuttingDown) {
      showStatus(`${label} failed`, error.message);
    }
  });
}

async function start() {
  try {
    checkPrerequisites();
    await ensureOllama();
    await ensureBackend();
    await ensureFrontend();
    showStatus("Opening RFP BidOS", "Loading desktop window...");
    await mainWindow.loadURL(FRONTEND_URL);
    mainWindow.setTitle(APP_TITLE);
  } catch (error) {
    showStatus("RFP BidOS could not start", error.message);
  }
}

function stopChild(child) {
  if (!child || child.killed) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"]);
    return;
  }
  child.kill("SIGTERM");
}

function cleanup() {
  shuttingDown = true;
  stopChild(started.frontend);
  stopChild(started.backend);
  stopChild(started.ollama);
}

app.whenReady().then(() => {
  createWindow();
  start();
});

app.on("window-all-closed", () => {
  cleanup();
  app.quit();
});

app.on("before-quit", cleanup);
