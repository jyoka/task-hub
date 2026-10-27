// pi's shellPath setting as pi itself reads it (SettingsManager.getShellPath through normalizePath, pi 1.4.0
// core/settings-manager.js and utils/paths.js), for task-groups.ts to hand to worker/group-shell: "~/bin/bash"
// must name the same shell under task-hub as without it. Node's own modules only, so the tests run it with node.
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

export function normalizeShellPath(shellPath: string, home: string = homedir()): string {
  if (shellPath === "~") {
    return home;
  }
  if (shellPath.startsWith("~/")) {
    return join(home, shellPath.slice(2));
  }
  if (/^file:\/\//.test(shellPath)) {
    return fileURLToPath(shellPath);
  }
  return shellPath;
}
