#!/usr/bin/env node
// task-hub's `[agents] durable` and `[resume] durable` (durable/README.md):
//   node <clone>/durable/dist/cli.js --session {session} {prompt}
// Node's warning that its SQLite is experimental would land in the task's log: it is dropped before the runner,
// which opens SQLite, is loaded. Other warnings are printed as usual.
process.removeAllListeners("warning");
process.on("warning", (warning) => {
	if (warning.name !== "ExperimentalWarning") process.stderr.write(`${warning.name}: ${warning.message}\n`);
});
process.stdout.on("error", () => {}); // task-hub gone (its pipe closed): the run still ends by itself

const { main } = await import("./runner.ts");
const code = await main(process.argv.slice(2));
// The model's connection (openai-codex) keeps the process alive after the session is closed: end it once the output is
// out, as task-hub waits for the agent to end
process.stdout.write("", () => process.exit(code));
setTimeout(() => process.exit(code), 2000);
