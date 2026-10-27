// The runner (dist/runner.js, as built) with pi-ai's faux provider in place of the model, for the tests here and for
// tests/test_task.py's DurableRunnerTest: `node durable/test/faux-agent.ts --session {session} {prompt}`.
// The faux model answers from the transcript alone, so a second process (after kill -9) goes on the same way:
//   1. a bash call that writes .tool-started, sleeps FAUX_SLEEP seconds (default 0), then writes slow-done.txt
//   2. after the bash result, a write of .task-report.md that says how the bash call ended and how many user inputs
//      the conversation holds (FAUX_MODE=noreport: an answer without it, until the runner asks for it)
//   3. after the write, the answer "Done."
// FAUX_CALLS, when set, is a file that gets one line per model request.
import { appendFileSync } from "node:fs";
import { createModels, fauxAssistantMessage, fauxProvider, fauxText, fauxToolCall } from "@earendil-works/pi-ai";
import { main, REPORT_FILE, REPORT_TEXT } from "../dist/runner.js";

const sleep = Number(process.env.FAUX_SLEEP ?? 0);
const mode = process.env.FAUX_MODE ?? "";

function said(content: unknown): string {
	if (typeof content === "string") return content;
	return Array.isArray(content) ? content.map((b) => (b?.type === "text" ? b.text : "")).join("\n") : "";
}

function brain(context: { messages: readonly any[] }) {
	const messages = context.messages;
	const last = messages[messages.length - 1];
	if (process.env.FAUX_CALLS) appendFileSync(process.env.FAUX_CALLS, `${last.role}${last.toolName ? ` ${last.toolName}` : ""}\n`);
	const users = messages.filter((m) => m.role === "user").length;
	const report = (bash: string) =>
		fauxAssistantMessage(
			[
				fauxText("Writing the report."),
				fauxToolCall("write", {
					path: REPORT_FILE,
					content: `## Report\n\n### Summary\n\n- The faux model wrote this. bash: ${bash}. user inputs: ${users}.\n\n### Details\n\nNone.\n\n## Please review\n\n- Nothing.\n`,
				}),
			],
			{ stopReason: "toolUse" },
		);
	if (last.role === "user") {
		if (said(last.content) === REPORT_TEXT) return report("asked for the report");
		return fauxAssistantMessage(
			[
				fauxText("Running the slow step first."),
				fauxToolCall("bash", { command: `echo started > .tool-started && sleep ${sleep} && echo finished > slow-done.txt` }),
			],
			{ stopReason: "toolUse" },
		);
	}
	if (last.role === "toolResult" && last.toolName === "bash") {
		const how = !last.isError ? "finished" : /interrupted/i.test(said(last.content)) ? "interrupted" : "failed";
		if (mode === "noreport") return fauxAssistantMessage(`Done without a report; bash ${how}.`);
		return report(how);
	}
	return fauxAssistantMessage("Done.");
}

const faux = fauxProvider({ provider: "faux", models: [{ id: "faux-1" }] });
// A factory per request: enough for any run (each step reads the transcript)
faux.setResponses(Array.from({ length: 50 }, () => brain));

process.stdout.on("error", () => {});
process.exitCode = await main(process.argv.slice(2).concat(process.argv.includes("--model") ? [] : ["--model", "faux/faux-1"]), {
	connect: async () => {
		const models = createModels();
		models.setProvider(faux.provider);
		return models;
	},
});
