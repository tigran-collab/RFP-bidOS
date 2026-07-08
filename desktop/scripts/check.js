const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const required = [
  "main.js",
  "status.html",
  "status-preload.js",
  "package.json",
  "assets/README.md",
];

for (const file of required) {
  const fullPath = path.join(__dirname, "..", file);
  if (!fs.existsSync(fullPath)) {
    console.error(`Missing desktop launcher file: ${file}`);
    process.exit(1);
  }
}

for (const file of ["main.js", "status-preload.js"]) {
  const fullPath = path.join(__dirname, "..", file);
  const result = spawnSync(process.execPath, ["--check", fullPath], {
    encoding: "utf8",
  });
  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  if (result.status !== 0) {
    process.stderr.write(result.stderr || result.stdout || `Syntax check failed for ${file}\n`);
    process.exit(result.status || 1);
  }
}

console.log("desktop launcher files ok");
