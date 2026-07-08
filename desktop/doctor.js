"use strict";

const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const OLLAMA_BASE_URL = "http://127.0.0.1:11434";
const OLLAMA_MODEL = "qwen3:8b";
const OLLAMA_MODEL_BASE = OLLAMA_MODEL.split(":")[0];

const desktopDir = __dirname;
const appRoot = path.resolve(desktopDir, "..");
const backendDir = path.join(appRoot, "backend");
const frontendDir = path.join(appRoot, "frontend");

function exists(filePath) {
  return fs.existsSync(filePath);
}

function isFile(filePath) {
  try {
    return fs.statSync(filePath).isFile();
  } catch {
    return false;
  }
}

function resolveCommand(command) {
  const fromPath = findCommandOnPath(command);
  if (fromPath) return fromPath;
  for (const candidate of commandCandidates(command)) {
    if (candidate && exists(candidate)) return candidate;
  }
  return null;
}

function backendPythonPath() {
  return process.platform === "win32"
    ? path.join(backendDir, ".venv", "Scripts", "python.exe")
    : path.join(backendDir, ".venv", "bin", "python");
}

function electronBinaryPath() {
  if (process.platform === "win32") {
    return path.join(desktopDir, "node_modules", "electron", "dist", "electron.exe");
  }
  if (process.platform === "darwin") {
    return path.join(desktopDir, "node_modules", "electron", "dist", "Electron.app");
  }
  return path.join(desktopDir, "node_modules", "electron", "dist", "electron");
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

function findCommandOnPath(command) {
  if (!command) return null;
  const value = String(command);
  if (path.isAbsolute(value) || value.includes(path.sep) || value.includes("/") || value.includes("\\")) {
    return exists(value) ? value : null;
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
      if (exists(candidate)) return candidate;
    }
  }
  return null;
}

function getJson(url, timeoutMs = 2500) {
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
    req.on("timeout", () => req.destroy(new Error(`${url} timed out`)));
    req.on("error", reject);
  });
}

function modelNames(tags) {
  return Array.isArray(tags?.models)
    ? tags.models.map((model) => model.name || model.model).filter(Boolean)
    : [];
}

function hasRequiredModel(names) {
  // Accept the exact tag, the "-latest" alias, or any tag sharing the model's
  // base name — e.g. a legit `qwen3` pulled as `qwen3:latest` still counts.
  return names.some((name) => {
    const normalized = String(name).toLowerCase();
    if (normalized === OLLAMA_MODEL || normalized === `${OLLAMA_MODEL}-latest`) {
      return true;
    }
    return normalized.split(":")[0] === OLLAMA_MODEL_BASE;
  });
}

function gitValue(args) {
  const result = spawnSync("git", args, { cwd: appRoot, encoding: "utf8", windowsHide: true });
  if (result.status !== 0) return null;
  return String(result.stdout || "").trim() || null;
}

function pythonImportCheck() {
  const python = backendPythonPath();
  if (!exists(python)) return { ok: false, detail: "backend venv Python missing" };
  const result = spawnSync(python, ["-c", "import fastapi, sqlmodel, uvicorn; print('ok')"], {
    cwd: backendDir,
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.error) {
    return { ok: false, warn: true, detail: result.error.message };
  }
  return {
    ok: result.status === 0,
    warn: false,
    detail: result.status === 0 ? "fastapi/sqlmodel/uvicorn import" : String(result.stderr || result.stdout || result.error?.message || "import failed").trim(),
  };
}

function print(status, label, detail = "") {
  const suffix = detail ? ` - ${detail}` : "";
  console.log(`${status} ${label}${suffix}`);
}

async function main() {
  const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
  const npmResolved = resolveCommand(npmCommand);
  const ollamaResolved = resolveCommand("ollama");
  const branch = gitValue(["branch", "--show-current"]);
  const commit = gitValue(["rev-parse", "--short", "HEAD"]);

  print("PASS", "platform", process.platform);
  print("PASS", "node version", process.version);
  print("PASS", "cwd", process.cwd());
  print("PASS", "appRoot", appRoot);
  print(appRoot === path.resolve(desktopDir, "..") ? "PASS" : "FAIL", "appRoot resolves from desktop", appRoot);
  print(exists(backendPythonPath()) ? "PASS" : "FAIL", "backend venv python", backendPythonPath());

  const imports = pythonImportCheck();
  print(imports.ok ? "PASS" : imports.warn ? "WARN" : "FAIL", "backend requirements import check", imports.detail);

  print(exists(path.join(frontendDir, "package.json")) ? "PASS" : "FAIL", "frontend package.json", path.join(frontendDir, "package.json"));
  print(exists(path.join(frontendDir, "node_modules")) ? "PASS" : "FAIL", "frontend node_modules", path.join(frontendDir, "node_modules"));
  print(exists(path.join(frontendDir, "package-lock.json")) ? "PASS" : "WARN", "frontend package-lock.json", path.join(frontendDir, "package-lock.json"));
  print(npmResolved ? "PASS" : "FAIL", npmCommand, npmResolved || "not found");
  print(ollamaResolved ? "PASS" : "FAIL", "ollama command", ollamaResolved || "not found");
  print(exists(electronBinaryPath()) ? "PASS" : "FAIL", "Electron binary", electronBinaryPath());
  print(isFile(electronBinaryPath()) || process.platform === "darwin" ? "PASS" : "FAIL", "Electron binary type", electronBinaryPath());
  print(branch ? "PASS" : "WARN", "git branch", branch || "not available");
  print(commit ? "PASS" : "WARN", "git commit", commit || "not available");

  try {
    const tags = await getJson(`${OLLAMA_BASE_URL}/api/tags`);
    print("PASS", "Ollama API reachable", `${OLLAMA_BASE_URL}/api/tags`);
    const names = modelNames(tags);
    print(hasRequiredModel(names) ? "PASS" : "FAIL", `${OLLAMA_MODEL} installed`, names.length ? names.join(", ") : "no models returned");
  } catch (error) {
    print("WARN", "Ollama API reachable", error.message);
    print("WARN", `${OLLAMA_MODEL} installed`, `start Ollama, then run: ollama pull ${OLLAMA_MODEL}`);
  }
}

main().catch((error) => {
  print("FAIL", "doctor failed", error.stack || error.message);
  process.exit(1);
});
