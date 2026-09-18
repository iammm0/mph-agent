#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const isWin = os.platform() === "win32";
const npm = isWin ? "npm.cmd" : "npm";

function run(command, args, cwd = desktopRoot) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    cwd,
    shell: isWin,
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

if (isWin) {
  run("powershell", [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "scripts/build-bridge.ps1",
  ]);
  run("powershell", [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "scripts/download-jdk11.ps1",
  ]);
  run(npm, ["run", "tauri", "--", "build", "--bundles", "nsis"]);
} else if (os.platform() === "darwin") {
  if (os.arch() !== "arm64") {
    console.error(
      "macOS desktop bundling currently targets Apple Silicon (arm64). This machine is " +
        os.arch() +
        "."
    );
    process.exit(1);
  }
  run("bash", ["scripts/build-bridge.sh"]);
  run("bash", ["scripts/download-jdk11.sh"]);
  run(npm, ["run", "tauri", "--", "build", "--bundles", "dmg"]);
} else {
  console.error(
    "Desktop bundling is only supported on Windows x64 and macOS Apple Silicon."
  );
  process.exit(1);
}
