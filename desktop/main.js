const { app, BrowserWindow } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const APP_TITLE = "RFP BidOS";
const OLLAMA_BASE_URL = "http://127.0.0.1:11434";
const OLLAMA_MODEL = "qwen3:8b";
const OLLAMA_START_TIMEOUT_MS = 30000;
const BACKEND_START_TIMEOUT_MS = 30000;
const FRONTEND_START_TIMEOUT_MS = 45000;
const BACKEND_URL = "http://127.0.0.1:8000";
const FRONTEND_URL = "http://localhost:5173";

const desktopDir = __dirname;
const appRoot = path.resolve(desktopDir, "..");
const backendDir = path.join(appRoot, "backend");
const frontendDir = path.join(appRoot, "frontend");
const logsDir = path.join(desktopDir, "logs");
const launchLogPath = path.join(logsDir, "launch.log");

const steps = [
  "Checking Ollama",
  "Starting Ollama if needed",
  `Checking ${OLLAMA_MODEL} model`,
  "Starting backend",
  "Starting frontend",
  "Opening RFP BidOS",
].map((label) => ({ label, status: "pending", detail: "" }));

const started = {
  ollama: null,
  backend: null,
  frontend: null,
};

let mainWindow = null;
let shuttingDown = false;
let cleanedUp = false;

function iconPath() {
  const candidates = process.platform === "win32"
    ? [path.join(desktopDir, "assets", "icon.ico"), path.join(desktopDir, "assets", "icon.png")]
    : process.platform === "darwin"
      ? [path.join(desktopDir, "assets", "icon.icns"), path.join(desktopDir, "assets", "icon.png")]
      : [path.join(desktopDir, "assets", "icon.png")];
  return candidates.find((candidate) => isFile(candidate));
}

function createWindow() {
  const icon = iconPath();
  const windowOptions = {
    width: 1280,
    height: 860,
    title: APP_TITLE,
    webPreferences: {
      preload: path.join(desktopDir, "status-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  };
  if (icon) {
    windowOptions.icon = icon;
  }

  logEvent("launcher:start", {
    platform: process.platform,
    appRoot,
    node: process.version,
    electron: process.versions.electron,
    icon: icon || "(omitted)",
  });
  mainWindow = new BrowserWindow(windowOptions);
  mainWindow.setTitle(APP_TITLE);
  return mainWindow.loadFile(path.join(desktopDir, "status.html")).then(() => {
    sendStartupStatus({
      title: "Starting RFP BidOS",
      message: "Preparing local services...",
      steps,
    });
  });
}

function setStep(label, status, detail = "") {
  const step = steps.find((item) => item.label === label || item.label.startsWith(label));
  if (step) {
    step.status = status;
    step.detail = detail;
  }
  logEvent("step", { label, status, detail });
  sendStartupStatus({
    step: step?.label || label,
    status,
    message: detail || label,
    steps,
  });
}

function showFailure(title, message, detail = "") {
  logEvent("failure", { title, message, detail });
  const failedStep = steps.find((step) => step.status === "failed");
  sendStartupStatus({
    title,
    step: failedStep?.label || "Startup",
    status: "error",
    message,
    error: message,
    detail,
    steps,
  });
}

function sendStartupStatus(payload) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send("startup-status", payload);
}

function commandExists(command) {
  return Boolean(resolveCommand(command));
}

function resolveCommand(command) {
  const fromPath = findCommandOnPath(command);
  if (fromPath) return fromPath;
  for (const candidate of commandCandidates(command)) {
    if (candidate && fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

function commandCandidates(command) {
  if (command !== "ollama") {
    return [];
  }
  if (process.platform === "win32") {
    return [
      process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Programs", "Ollama", "ollama.exe"),
      process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, "Ollama", "ollama.exe"),
      process.env["PROGRAMFILES(X86)"] && path.join(process.env["PROGRAMFILES(X86)"], "Ollama", "ollama.exe"),
    ].filter(Boolean);
  }
  if (process.platform === "darwin") {
    return [
      "/opt/homebrew/bin/ollama",
      "/usr/local/bin/ollama",
      "/Applications/Ollama.app/Contents/Resources/ollama",
    ];
  }
  return ["/usr/local/bin/ollama", "/usr/bin/ollama"];
}

function pythonPath() {
  return process.platform === "win32"
    ? path.join(backendDir, ".venv", "Scripts", "python.exe")
    : path.join(backendDir, ".venv", "bin", "python");
}

function checkPrerequisites() {
  const missing = [];
  if (!fs.existsSync(pythonPath())) {
    missing.push(venvMissingMessage());
  }
  if (!fs.existsSync(path.join(frontendDir, "package.json"))) {
    missing.push("frontend/package.json is missing.");
  }
  if (!fs.existsSync(path.join(frontendDir, "node_modules"))) {
    missing.push("Frontend dependencies are missing.\nRun: cd frontend && npm install");
  }
  if (!commandExists(process.platform === "win32" ? "npm.cmd" : "npm")) {
    missing.push("npm is not installed or not on PATH.");
  }
  if (missing.length) {
    logEvent("preflight:failed", { missing });
    throw new Error(missing.join("\n\n"));
  }
  logEvent("preflight:passed", {
    backendPython: pythonPath(),
    frontendPackage: path.join(frontendDir, "package.json"),
    frontendNodeModules: path.join(frontendDir, "node_modules"),
    npm: resolveCommand(process.platform === "win32" ? "npm.cmd" : "npm"),
  });
}

function venvMissingMessage() {
  if (process.platform === "win32") {
    return "Backend virtual environment is missing.\nRun: cd backend && python -m venv .venv && .venv\\Scripts\\activate.bat && python -m pip install -r requirements.txt";
  }
  return "Backend virtual environment is missing.\nRun: cd backend && python3 -m venv .venv && . .venv/bin/activate && python -m pip install -r requirements.txt";
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
  setStep("Checking Ollama", "running", "Checking Ollama API...");
  let tags = await tryOllamaTags();
  if (tags) {
    setStep("Checking Ollama", "done", "Ollama is already running.");
  } else {
    setStep("Checking Ollama", "done", "Ollama API is not reachable.");
    setStep("Starting Ollama if needed", "running", "Starting ollama serve...");
    const ollamaCommand = resolveCommand("ollama");
    if (!ollamaCommand) {
      setStep("Starting Ollama if needed", "failed", "Ollama is not installed or not in PATH.");
      throw new Error(`Ollama is not installed or not in PATH.\nInstall Ollama, then run: ollama pull ${OLLAMA_MODEL}`);
    }
    started.ollama = spawnLogged("Ollama", ollamaCommand, ["serve"], {
      cwd: appRoot,
      shell: process.platform === "win32",
      env: process.env,
      stdio: "pipe",
      windowsHide: false,
    });
    try {
      await waitForUrl(`${OLLAMA_BASE_URL}/api/tags`, OLLAMA_START_TIMEOUT_MS, "Ollama");
      setStep("Starting Ollama if needed", "done", "Ollama started.");
    } catch (error) {
      setStep("Starting Ollama if needed", "failed", "Ollama could not be started.");
      throw new Error("Ollama could not be started. Install Ollama or start it manually, then relaunch RFP BidOS.");
    }
    tags = await tryOllamaTags();
  }

  setStep(`Checking ${OLLAMA_MODEL} model`, "running", `Checking for ${OLLAMA_MODEL}...`);
  const names = modelNames(tags);
  logEvent("ollama:models", { names });
  if (!hasRequiredModel(names)) {
    setStep(`Checking ${OLLAMA_MODEL} model`, "failed", `${OLLAMA_MODEL} is not installed.`);
    throw new Error(`Ollama is running, but ${OLLAMA_MODEL} is not installed.\nRun this command once: ollama pull ${OLLAMA_MODEL}`);
  }
  setStep(`Checking ${OLLAMA_MODEL} model`, "done", `${OLLAMA_MODEL} is available.`);
}

async function tryOllamaTags() {
  try {
    return await getJson(`${OLLAMA_BASE_URL}/api/tags`, 3000);
  } catch (error) {
    logEvent("ollama:tags-unreachable", { message: error.message });
    return null;
  }
}

function modelNames(tags) {
  return Array.isArray(tags?.models)
    ? tags.models.map((model) => model.name || model.model).filter(Boolean)
    : [];
}

function hasRequiredModel(names) {
  return names.some((name) => {
    const normalized = String(name).toLowerCase();
    return normalized === OLLAMA_MODEL || normalized === `${OLLAMA_MODEL}-latest` || normalized === "qwen3";
  });
}

async function ensureBackend() {
  setStep("Starting backend", "running", "Checking FastAPI backend...");
  const backendHealthReady = await urlReady(`${BACKEND_URL}/health`);
  if (backendHealthReady && await urlReady(`${BACKEND_URL}/ai/chat/status`)) {
    setStep("Starting backend", "done", "Backend is already running.");
    return;
  }
  if (backendHealthReady) {
    setStep("Starting backend", "failed", "Another backend is running on port 8000.");
    throw new Error("A backend is already running on 127.0.0.1:8000, but it does not have the Local AI Chat endpoints. Stop the old backend process and relaunch RFP BidOS.");
  }

  started.backend = spawnLogged("Backend", pythonPath(), [
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
  ], {
    cwd: backendDir,
    shell: false,
    env: {
      ...process.env,
      OLLAMA_BASE_URL,
      OLLAMA_MODEL,
    },
    stdio: "pipe",
    windowsHide: true,
  });
  try {
    await waitForUrl(`${BACKEND_URL}/health`, BACKEND_START_TIMEOUT_MS, "Backend");
    setStep("Starting backend", "done", "Backend is ready.");
  } catch (error) {
    setStep("Starting backend", "failed", "Backend could not be started.");
    const detail = processLogDetail(started.backend._rfpSpawnInfo, `Error: ${error.message}`, started.backend._rfpStderr || started.backend._rfpOutput || "");
    throw new Error(`Backend could not be started.\n\n${detail}`);
  }
}

async function ensureFrontend() {
  setStep("Starting frontend", "running", "Checking Vite frontend...");
  if (await urlReady(FRONTEND_URL)) {
    setStep("Starting frontend", "done", "Frontend is already running.");
    return;
  }

  const npmCommand = resolveCommand(process.platform === "win32" ? "npm.cmd" : "npm") || (process.platform === "win32" ? "npm.cmd" : "npm");
  const frontendCommand = process.platform === "win32" ? "cmd.exe" : npmCommand;
  const frontendArgs = process.platform === "win32" ? ["/d", "/c", "npm.cmd run dev"] : ["run", "dev"];
  started.frontend = spawnLogged("Frontend", frontendCommand, frontendArgs, {
    cwd: frontendDir,
    shell: false,
    env: {
      ...process.env,
      VITE_API_BASE_URL: BACKEND_URL,
    },
    stdio: "pipe",
    windowsHide: true,
  });
  try {
    await waitForUrl(FRONTEND_URL, FRONTEND_START_TIMEOUT_MS, "Frontend");
    setStep("Starting frontend", "done", "Frontend is ready.");
  } catch (error) {
    setStep("Starting frontend", "failed", "Frontend could not be started.");
    const detail = processLogDetail(started.frontend._rfpSpawnInfo, `Error: ${error.message}`, started.frontend._rfpStderr || started.frontend._rfpOutput || "");
    throw new Error(`Frontend could not be started. Run npm install in the frontend folder and relaunch.\n\n${detail}`);
  }
}

async function urlReady(url) {
  try {
    await waitForUrl(url, 1000, url);
    return true;
  } catch {
    return false;
  }
}

function spawnLogged(label, command, args, options) {
  const spawnInfo = buildProcessInfo(label, command, args, options);
  logEvent(`${label}:spawn`, spawnInfo);
  let child;
  try {
    child = spawn(command, args, options);
  } catch (error) {
    logProcessError(label, error, spawnInfo);
    throw error;
  }
  child._rfpSpawnInfo = spawnInfo;
  attachProcessLogging(label, child, spawnInfo);
  return child;
}

function spawnSyncLogged(label, command, args, options = {}) {
  const spawnInfo = buildProcessInfo(label, command, args, options);
  logEvent(`${label}:spawnSync`, spawnInfo);
  let result;
  try {
    result = spawnSync(command, args, options);
  } catch (error) {
    logProcessError(label, error, spawnInfo);
    throw error;
  }
  if (result.error) {
    logProcessError(label, result.error, spawnInfo);
  }
  if (result.status !== 0 || result.error) {
    logEvent(`${label}:spawnSync-result`, {
      status: result.status,
      signal: result.signal || null,
      stderr: truncate(result.stderr),
      stdout: truncate(result.stdout),
    });
  }
  return result;
}

function buildProcessInfo(label, command, args = [], options = {}) {
  return {
    label,
    command: String(command),
    args: Array.isArray(args) ? args.map(String) : args,
    formattedCommand: formatCommand(command, args),
    cwd: options.cwd || process.cwd(),
    shell: options.shell === undefined ? false : options.shell,
    detached: options.detached === undefined ? false : options.detached,
    platform: process.platform,
    pathPresent: Boolean((options.env || process.env).PATH || (options.env || process.env).Path),
    pathLength: String((options.env || process.env).PATH || (options.env || process.env).Path || "").length,
    targetExists: commandTargetExists(command),
  };
}

function formatCommand(command, args = []) {
  return [command, ...args].map((part) => {
    const value = String(part);
    return /\s/.test(value) ? `"${value}"` : value;
  }).join(" ");
}

function attachProcessLogging(label, child, spawnInfo) {
  let output = "";
  let stderr = "";
  const append = (stream, chunk) => {
    const text = chunk.toString();
    output = `${output}${text}`.slice(-12000);
    child._rfpOutput = output;
    if (stream === "stderr") {
      stderr = `${stderr}${text}`.slice(-12000);
      child._rfpStderr = stderr;
    }
    logEvent(`${label}:${stream}`, { text: truncate(text) });
  };
  child.stdout?.on("data", (chunk) => append("stdout", chunk));
  child.stderr?.on("data", (chunk) => append("stderr", chunk));
  child.on("exit", (code, signal) => {
    logEvent(`${label}:exit`, { code, signal: signal || null, output: truncate(output), stderr: truncate(stderr) });
    if (!shuttingDown && code !== 0 && code !== null) {
      const detail = processLogDetail(spawnInfo, `Exit code: ${code}\nSignal: ${signal || "-"}`, stderr || output);
      showFailure(`${label} stopped`, `${label} exited before the launcher closed.`, detail);
    }
  });
  child.on("error", (error) => {
    if (!shuttingDown) {
      const detail = processLogDetail(spawnInfo, `Error: ${error.message}`, stderr);
      logProcessError(label, error, spawnInfo);
      showFailure(`${label} failed`, error.message, detail);
    }
  });
}

function processLogDetail(spawnInfo, message, stderr = "") {
  return [
    `Label: ${spawnInfo.label}`,
    `Command: ${spawnInfo.formattedCommand || spawnInfo.command}`,
    `CWD: ${spawnInfo.cwd}`,
    `Shell: ${spawnInfo.shell}`,
    `Detached: ${spawnInfo.detached}`,
    `Platform: ${spawnInfo.platform}`,
    `PATH present: ${spawnInfo.pathPresent}`,
    `PATH length: ${spawnInfo.pathLength}`,
    `Target exists: ${spawnInfo.targetExists}`,
    message,
    stderr ? `stderr:\n${stderr}` : "stderr: -",
  ].join("\n");
}

function logProcessError(label, error, spawnInfo) {
  logEvent(`${label}:error`, {
    label,
    command: spawnInfo?.formattedCommand || spawnInfo?.command,
    cwd: spawnInfo?.cwd,
    shell: spawnInfo?.shell,
    detached: spawnInfo?.detached,
    platform: process.platform,
    targetExists: spawnInfo?.targetExists,
    errorName: error.name,
    errorCode: error.code,
    errorErrno: error.errno,
    errorSyscall: error.syscall,
    errorPath: error.path,
    errorSpawnargs: error.spawnargs,
    errorMessage: error.message,
    stack: error.stack,
  });
}

function logEvent(label, detail = {}) {
  const entry = `[${new Date().toISOString()}] ${label}\n${JSON.stringify(detail, null, 2)}\n`;
  console.log(entry);
  try {
    fs.mkdirSync(logsDir, { recursive: true });
    fs.appendFileSync(launchLogPath, entry, "utf8");
  } catch {
    // Console logging still works if the log file cannot be written.
  }
}

function commandTargetExists(command) {
  if (!command) return false;
  const value = String(command);
  if (path.isAbsolute(value) || value.includes(path.sep) || value.includes("/") || value.includes("\\")) {
    return fs.existsSync(value);
  }
  if (process.platform === "win32") {
    const extensions = (process.env.PATHEXT || ".COM;.EXE;.BAT;.CMD").split(";").filter(Boolean);
    const names = path.extname(value) ? [value] : [value, ...extensions.map((ext) => `${value}${ext.toLowerCase()}`), ...extensions.map((ext) => `${value}${ext.toUpperCase()}`)];
    return Boolean(findOnPath(names));
  }
  return Boolean(findOnPath([value]));
}

function findCommandOnPath(command) {
  if (!command) return null;
  const value = String(command);
  if (path.isAbsolute(value) || value.includes(path.sep) || value.includes("/") || value.includes("\\")) {
    return fs.existsSync(value) ? value : null;
  }
  if (process.platform === "win32") {
    const extensions = (process.env.PATHEXT || ".COM;.EXE;.BAT;.CMD").split(";").filter(Boolean);
    const names = path.extname(value) ? [value] : [
      value,
      ...extensions.map((ext) => `${value}${ext.toLowerCase()}`),
      ...extensions.map((ext) => `${value}${ext.toUpperCase()}`),
    ];
    return findOnPath(names);
  }
  return findOnPath([value]);
}

function findOnPath(names) {
  const pathValue = process.env.PATH || process.env.Path || "";
  for (const dir of pathValue.split(path.delimiter).filter(Boolean)) {
    for (const name of names) {
      const candidate = path.join(dir, name);
      if (fs.existsSync(candidate)) {
        return candidate;
      }
    }
  }
  return null;
}

function isFile(filePath) {
  try {
    return fs.statSync(filePath).isFile();
  } catch {
    return false;
  }
}

function truncate(value) {
  if (!value) return "";
  return String(value).slice(-4000);
}

async function start() {
  try {
    checkPrerequisites();
    await ensureOllama();
    await ensureBackend();
    await ensureFrontend();
    setStep("Opening RFP BidOS", "running", "Loading app window...");
    await mainWindow.loadURL(FRONTEND_URL);
    mainWindow.setTitle(APP_TITLE);
    const step = steps.find((item) => item.label === "Opening RFP BidOS");
    if (step) {
      step.status = "done";
      step.detail = "RFP BidOS is open.";
    }
    logEvent("step", { label: "Opening RFP BidOS", status: "done", detail: "RFP BidOS is open." });
  } catch (error) {
    logProcessError("Launcher", error, { label: "Launcher", formattedCommand: "startup", cwd: appRoot, shell: false, detached: false, platform: process.platform, targetExists: true });
    showFailure("RFP BidOS could not start", error.message);
  }
}

function stopChild(label, child) {
  if (!child || child.killed || !child.pid) return;
  if (process.platform === "win32") {
    spawnSyncLogged(`Cleanup ${label}`, "taskkill.exe", ["/pid", String(child.pid), "/T", "/F"], {
      windowsHide: true,
      encoding: "utf8",
    });
    return;
  }
  child.kill("SIGTERM");
}

function cleanup() {
  if (cleanedUp) return;
  cleanedUp = true;
  shuttingDown = true;
  stopChild("frontend", started.frontend);
  stopChild("backend", started.backend);
  stopChild("ollama", started.ollama);
}

app.whenReady().then(async () => {
  await createWindow();
  start();
});

app.on("window-all-closed", () => {
  cleanup();
  app.quit();
});

app.on("before-quit", cleanup);
process.on("SIGINT", () => {
  cleanup();
  process.exit(0);
});
process.on("SIGTERM", () => {
  cleanup();
  process.exit(0);
});
