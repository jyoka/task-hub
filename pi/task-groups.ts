// Runs pi's bash tool through task-hub's worker/group-shell while task-hub runs pi as a task's agent, so that what a
// cut-short agent left running (a long test) is stopped before the task's next agent starts (lld.md 7).
//
// pi starts each bash command in a process group of its own, which stopping the agent's group does not reach.
// group-shell notes that group while the command runs; task-hub stops the ones left before it starts an agent again.
// task-hub's built-in [agents] pi loads this file with -e (which --no-extensions leaves on). It does nothing unless
// task-hub set TASK_HUB_GROUPS, and never writes pi's settings: it reads them for the shell and its prefix.
import { createBashToolDefinition, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { normalizeShellPath } from "./shell-path.ts";

export default function (pi: ExtensionAPI) {
  const groupShell = process.env.TASK_HUB_GROUP_SHELL;
  if (!process.env.TASK_HUB_GROUPS || !groupShell || process.platform === "win32") {
    return;
  }
  // Once every extension is loaded, not while loading: two extensions that register "bash" stop pi from starting
  // (`Tool "bash" conflicts with ...`). The same name as the built-in tool replaces it (examples/extensions/tool-override.ts).
  pi.on("session_start", () => {
    try {
      if (pi.getAllTools().some((tool) => tool.name === "bash" && !tool.sourceInfo.path.startsWith("builtin:"))) {
        return; // another extension's bash (a sandbox, ssh) is left as it is: its commands go unnoted
      }
      const settings = pi.getSettings(); // pi's own reading: global and, if trusted, the project's
      if (settings.shellPath) {
        // group-shell runs the command with it, as pi would have: ~ and file:// URLs read as pi reads them
        process.env.TASK_HUB_SHELL = normalizeShellPath(settings.shellPath);
      }
      pi.registerTool(
        createBashToolDefinition(process.cwd(), { shellPath: groupShell, commandPrefix: settings.shellCommandPrefix }),
      );
    } catch {
      // noting is never worth a bash that cannot run: pi's own stays
    }
  });
}
