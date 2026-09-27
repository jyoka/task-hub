// Wakes a Pi session when task-hub's board changes, so /skill:chief can tell the user without being asked.
//
// Pi has no background commands: an agent cannot start `task events --next` and be woken when it exits.
// This extension does that loop itself and hands each batch of events to the session as a message.
// Install: ln -sfn ~/.local/lib/task-hub/pi/task-events.ts ~/.pi/agent/extensions/task-events.ts
import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, join } from "node:path";

const DEFAULT_ONLY = "In review,Blocked,replan,Done,slow";

// `task` on PATH, else the usual install (the same rule the skills follow)
function taskBin(): string {
  const onPath = (process.env.PATH ?? "").split(delimiter).map((dir) => join(dir, "task")).find((f) => existsSync(f));
  return onPath ?? join(homedir(), ".local/lib/task-hub/bin/task");
}

export default function (pi: ExtensionAPI) {
  let watching: AbortController | undefined;

  function stop(): void {
    watching?.abort();
    watching = undefined;
  }

  function tell(content: string, details: unknown): void {
    try {
      pi.sendMessage(
        { customType: "task-hub-events", content, display: true, details },
        { triggerTurn: true, deliverAs: "followUp" },
      );
    } catch {
      // the session may already be gone
    }
  }

  // `task events --next` prints the events and the command that continues right after them, then exits.
  // Following that cursor loses nothing that happens between two runs.
  async function watch(only: string, signal: AbortSignal): Promise<void> {
    let after: string | undefined;
    while (!signal.aborted) {
      const args = ["events", "--next", ...(after ? ["--after", after] : []), "--only", only];
      const result = await pi.exec(taskBin(), args, { signal }).catch(() => undefined);
      if (signal.aborted) return;
      const lines = result?.stdout.split("\n") ?? [];
      const cursor = lines.find((line) => line.startsWith("next:"))?.match(/--after (\d+)/)?.[1];
      if (!result || result.code !== 0 || !cursor) {
        const why = result ? (result.stderr || result.stdout).trim().split("\n").at(-1) : "could not run task";
        tell(`task-hub events: watching stopped (${why}). Tell the user, then call task_events_watch again.`, { why });
        stop();
        return;
      }
      after = cursor;
      const events = lines.filter((line) => line.startsWith("event:"));
      if (events.length) {
        tell(`task-hub events:\n${events.join("\n")}\n\nHandle them as the chief skill says.`, { events });
      }
    }
  }

  pi.registerTool(
    defineTool({
      name: "task_events_watch",
      label: "task-hub events",
      description:
        "Start watching the task-hub board for the chief skill. Each new event (In review, Blocked, replan, Done) " +
        "arrives later as a message that wakes you. Call it once per session; do not poll or call it again unless " +
        "a message says watching stopped.",
      promptSnippet: "Watch task-hub events; they arrive as messages",
      parameters: Type.Object({
        only: Type.Optional(Type.String({ description: `Comma-separated events to watch, default "${DEFAULT_ONLY}"` })),
      }),
      async execute(_id, params) {
        if (watching) {
          return { content: [{ type: "text", text: "Already watching task-hub events." }], details: undefined };
        }
        watching = new AbortController();
        void watch(params.only || DEFAULT_ONLY, watching.signal);
        return {
          content: [{ type: "text", text: "Watching task-hub events. They will arrive as messages; do not poll." }],
          details: undefined,
        };
      },
    }),
  );

  pi.on("session_shutdown", () => stop());
}
