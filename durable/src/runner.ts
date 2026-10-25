// The Pi Durable runner (docs/architecture/designs/durable-runs.md, "B: Pi Durable の実行役"): one task-hub agent.
// It keeps the conversation and the tool calls under way in `.task-durable/<session>.sqlite` in the worktree, and a
// second start with the same --session goes on from there (harness.resume()) instead of from the prompt again.
// task-hub starts it the same way the first time and to resume, so it never tells agents apart by name.
import { spawnSync } from "node:child_process";
import { closeSync, existsSync, mkdirSync, openSync, readdirSync, readFileSync, rmSync, unlinkSync, writeFileSync, writeSync } from "node:fs";
import { isAbsolute, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import type { Models, ModelThinkingLevel } from "@earendil-works/pi-ai";
import {
	AssistantEntry,
	createRegistry,
	DEFAULT_RESTART_LIMIT,
	defineExtension,
	GenerationTask,
	Harness,
	hook,
	section,
	ToolTask,
} from "@earendil-works/pi-durable";
import { NodeExecutionEnv } from "@earendil-works/pi-durable/env/node";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { CodingTools } from "@earendil-works/pi-durable/tools";
import { AuthFailed, connect, defaultAuthPath } from "./auth.ts";

/** Exit codes: answered, failed (the model, the login, the arguments), the session is in use, parked (restart_limit). */
export const EXIT = { answered: 0, failed: 1, locked: 2, parked: 3 } as const;
export const DIR = ".task-durable";
export const REPORT_FILE = ".task-report.md";
export const MODEL = "openai-codex/gpt-6-luna";
// pi's own default (DEFAULT_THINKING_LEVEL in pi-coding-agent 1.4.0), given explicitly, so that A (pi) and B think
// alike (durable-runs.md, decision 7)
export const THINKING = "medium";
const THINKING_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
// The inputs, by requestId: a second start finds the one already admitted instead of submitting it again
export const FIRST = "task-hub:first";
export const CONTINUE = "task-hub:continue";
export const REPORT = "task-hub:report";
export const CONTINUE_TEXT = "The last attempt to answer failed before it ended. Go on with the task from where it stopped.";
export const REPORT_TEXT = `You ended without writing ${REPORT_FILE}. Write it now, in the form the task asks for.`;
// The bash tool's shell, which notes each command's process group (scripts/group-shell). Not on Windows
const GROUP_SHELL = process.platform === "win32" ? undefined : fileURLToPath(new URL("../scripts/group-shell", import.meta.url));
const CLOSE_MS = 5000; // how long a signal waits for the Harness to close before the runner ends anyway

const USAGE = `usage: node durable/dist/cli.js --session <id> [--model <provider/model>] [--thinking <level>]
                  [--auth <pi's auth.json>] [--restart-limit <n>] <prompt>`;

export type Options = {
	session: string;
	prompt: string;
	model: string;
	thinking: string;
	authPath: string;
	restartLimit: number;
};

export type Deps = {
	/** The models to use: pi's login by default (auth.ts); the tests give pi-ai's faux provider. */
	connect?: (options: Options) => Promise<Models>;
	/** One line of output; stdout by default. */
	out?: (line: string) => void;
	cwd?: string;
	env?: NodeJS.ProcessEnv;
};

export function parseArgs(argv: readonly string[], env: NodeJS.ProcessEnv = process.env): Options | string {
	const options: Partial<Options> = { model: MODEL, thinking: THINKING, restartLimit: DEFAULT_RESTART_LIMIT };
	const rest: string[] = [];
	for (let i = 0; i < argv.length; i++) {
		const arg = argv[i];
		const value = () => {
			const v = argv[++i];
			if (v === undefined) throw new Error(`${arg} needs a value`);
			return v;
		};
		try {
			if (arg === "--") rest.push(...argv.slice(i + 1));
			else if (arg === "--session") options.session = value();
			else if (arg === "--model") options.model = value();
			else if (arg === "--thinking") options.thinking = value();
			else if (arg === "--auth") options.authPath = value();
			else if (arg === "--restart-limit") options.restartLimit = Number(value());
			else if (arg.startsWith("--")) return `unknown option ${arg}`;
			else rest.push(arg);
		} catch (error) {
			return (error as Error).message;
		}
		if (arg === "--") break;
	}
	if (!options.session) return "--session is required";
	// a file name in .task-durable/: never a path
	if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(options.session)) return `--session ${options.session}: letters, digits, . _ - only`;
	if (rest.length !== 1) return `one prompt, as one argument (got ${rest.length})`;
	if (!/^[^/]+\/.+$/.test(options.model!)) return `--model ${options.model}: give <provider>/<model>`;
	if (!THINKING_LEVELS.includes(options.thinking!)) return `--thinking ${options.thinking}: one of ${THINKING_LEVELS.join(", ")}`;
	if (!(options.restartLimit! >= 1)) return "--restart-limit: 1 or more";
	return { ...options, prompt: rest[0], authPath: options.authPath ?? defaultAuthPath(env) } as Options;
}

/** Whether pid is a live process (another user's counts: it is there). */
function alive(pid: number): boolean {
	try {
		process.kill(pid, 0);
		return true;
	} catch (error) {
		return (error as NodeJS.ErrnoException).code === "EPERM";
	}
}

/**
 * Pi Durable lets one process own a storage and has no lock between processes: `<session>.lock`, made with O_EXCL,
 * holds the owner's pid. A lock whose process is gone (kill -9) is taken over. Returns the live owner's pid, or 0.
 */
export function takeLock(path: string): number {
	for (let tries = 0; tries < 3; tries++) {
		try {
			const fd = openSync(path, "wx");
			writeSync(fd, `${process.pid}\n`);
			closeSync(fd);
			return 0;
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
		}
		let owner: string;
		try {
			owner = readFileSync(path, "utf8").trim();
		} catch {
			continue; // its owner just let it go
		}
		const pid = Number.parseInt(owner, 10);
		if (pid > 0 && pid !== process.pid && alive(pid)) return pid;
		try {
			unlinkSync(path);
		} catch {
			// another start took it over first: try again
		}
	}
	return -1;
}

export function dropLock(path: string): void {
	try {
		if (readFileSync(path, "utf8").trim() === String(process.pid)) unlinkSync(path);
	} catch {
		// not there, or not ours
	}
}

/** The step as task-hub's tool_step shows one: `bash: npm test`, `edit: src/x.ts`. */
export function step(name: string, args: unknown, cwd: string): string {
	if (!args || typeof args !== "object") return name;
	const a = args as Record<string, unknown>;
	const key = ["command", "path"].find((k) => typeof a[k] === "string" && (a[k] as string).trim());
	if (!key) return name;
	const lines = (a[key] as string).trim().split("\n");
	let value = lines[0] + (lines.length > 1 ? " ..." : "");
	if (key === "path" && isAbsolute(value)) {
		const inside = relative(cwd, value);
		if (inside && !inside.startsWith("..") && !isAbsolute(inside)) value = inside;
	}
	return `${name}: ${value}`;
}

/**
 * Stops what the bash tool of an earlier start of the session left running: Pi Durable starts each command in a
 * process group of its own, which a kill -9 of the runner's group does not reach. groups: the folder where
 * scripts/group-shell keeps a file per command, named after its group and holding the start time of its leader.
 * A file stays behind also when Pi Durable SIGKILLed the command (timeout, abort, close on SIGTERM), so a group is
 * stopped only while its leader is still that group-shell; any other file is just taken away.
 */
export function stopLeftovers(groups: string, out: (line: string) => void): void {
	let ids: number[];
	try {
		ids = readdirSync(groups).map(Number).filter((n) => Number.isInteger(n) && n > 1);
	} catch {
		return;
	}
	for (const id of ids) {
		let started = "";
		try {
			started = readFileSync(join(groups, String(id)), "utf8").trim();
		} catch {
			// it ended already
		}
		if (!started || leaderStart(id) !== started) continue;
		try {
			process.kill(-id, "SIGKILL");
			out(`durable: stopped process group ${id}, which a command of the run cut short left running`);
		} catch {
			// it ended already
		}
	}
	rmSync(groups, { recursive: true, force: true });
}

/** The start time (ps lstart) of process id when it lives and leads its own process group, else undefined. */
function leaderStart(id: number): string | undefined {
	const ps = spawnSync("ps", ["-o", "pgid=,lstart=", "-p", String(id)], { encoding: "utf8", env: { ...process.env, LC_ALL: "C" } });
	const found = ps.status === 0 ? /^\s*(\d+)\s+(.+?)\s*$/.exec(ps.stdout) : null;
	return found && Number(found[1]) === id ? found[2] : undefined;
}

function text(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.filter((b) => b && typeof b === "object" && b.type === "text" && typeof b.text === "string")
		.map((b) => b.text)
		.join("\n");
}

function firstLine(s: string): string {
	return s.split("\n").map((l) => l.trim()).find((l) => l) ?? "";
}

function parkedReport(cwd: string, limit: number, kind: string): void {
	const path = join(cwd, REPORT_FILE);
	const earlier = existsSync(path) ? readFileSync(path, "utf8") : "";
	const blocked = `## Blocked

durable runner: restart_limit: Pi Durable parked a step (${kind}) that was cut short ${limit} time(s) in a row, so it is not run again on its own; read the log, then move the card back to Ready to start over in a new session.
`;
	const report = `
## Report

### Summary

- The durable runner stopped: a step (${kind}) was cut short ${limit} time(s) in a row, and Pi Durable parked it (restart_limit).
- Nothing was checked after that: the run did not go on.

### Details

The conversation so far is in ${DIR}/ in the worktree. A new run (the card back to Ready) starts a new session.

## Please review

- The log of the run: what cut the step short each time.
`;
	writeFileSync(path, earlier ? `${blocked}\n${earlier}` : blocked + report);
}

export async function main(argv: readonly string[], deps: Deps = {}): Promise<number> {
	const out = deps.out ?? ((line: string) => void process.stdout.write(`${line}\n`));
	const cwd = deps.cwd ?? process.cwd();
	const parsed = parseArgs(argv, deps.env ?? process.env);
	if (typeof parsed === "string") {
		out(`durable: ${parsed}\n${USAGE}`);
		return EXIT.failed;
	}
	const options = parsed;
	const dir = join(cwd, DIR);
	mkdirSync(dir, { recursive: true });
	writeFileSync(join(dir, ".gitignore"), "*\n"); // never committed: task-hub commits what git does not ignore
	const lock = join(dir, `${options.session}.lock`);
	const owner = takeLock(lock);
	if (owner !== 0) {
		out(`durable: session ${options.session} is in use${owner > 0 ? ` by process ${owner}` : ""} (${DIR}/${options.session}.lock)`);
		return EXIT.locked;
	}
	try {
		return await run(options, cwd, dir, out, deps);
	} finally {
		dropLock(lock);
	}
}

async function run(options: Options, cwd: string, dir: string, out: (line: string) => void, deps: Deps): Promise<number> {
	const context = BACKGROUND_CONTEXT;
	let models: Models;
	try {
		models = await (deps.connect ?? ((o: Options) => connect(o.authPath)))(options);
	} catch (error) {
		if (error instanceof AuthFailed) {
			out(`durable: ${error.message}`);
			return EXIT.failed;
		}
		throw error;
	}
	const slash = options.model.indexOf("/");
	const model = { provider: options.model.slice(0, slash), modelId: options.model.slice(slash + 1) };
	if (!models.getModel(model.provider, model.modelId)) {
		out(`durable: no model ${options.model}`);
		return EXIT.failed;
	}

	const file = join(dir, `${options.session}.sqlite`);
	const reopened = existsSync(file);
	const groups = join(dir, `${options.session}.groups`);
	stopLeftovers(groups, out); // before anything runs again: never two writers in one worktree
	let onParked: (kind: string) => void = () => {};
	const parked = new Promise<string>((resolve) => {
		onParked = resolve;
	});
	const registry = createRegistry();
	registry.install(CodingTools);
	registry.install(
		defineExtension({
			name: "task-hub",
			sections: [
				section(
					"preamble",
					() =>
						`You are a coding agent. You work in ${cwd}, a git worktree, with the tools read, write, edit, and bash. ` +
						"Do the task in the user's message.",
					{ tag: false },
				),
			],
			hooks: [
				// before its intent is stored: a call that a restart cut short is not shown twice
				hook(ToolTask, {
					beforeTool: (call) => {
						if (!call.parent) out(`· ${step(call.name, call.arguments, cwd)}`);
						return undefined;
					},
				}),
				hook(GenerationTask, {
					afterResponse: (message) => {
						const said = firstLine(text(message.content));
						if (said && message.content.some((b) => b.type === "toolCall")) out(said); // the answer comes whole, at the end
					},
				}),
			],
		}),
	);
	const harness = await Harness.open(
		await openNodeSqliteStorage(file),
		{
			models,
			registry,
			env: (target) =>
				new NodeExecutionEnv({ cwd: target.cwd ?? cwd, shellPath: GROUP_SHELL, shellEnv: { TASK_DURABLE_GROUPS: groups } }),
			settings: { restartLimit: options.restartLimit },
			onReport: (_error, info) => {
				if (info.type === "task_parked") onParked(info.task.kind);
				else if (info.type !== "listener_error") out(`durable: ${info.type}${"task" in info ? ` (${info.task.kind})` : ""}`);
			},
		},
		context,
	);
	const stop = async (signal: NodeJS.Signals) => {
		out(`durable: stopped by ${signal}`);
		await Promise.race([harness.close(context), new Promise((r) => setTimeout(r, CLOSE_MS).unref())]);
		dropLock(join(dir, `${options.session}.lock`));
		process.kill(process.pid, signal); // ends by the signal, as task-hub expects of a killed agent
	};
	const signals: NodeJS.Signals[] = ["SIGTERM", "SIGHUP", "SIGINT"];
	const handlers = signals.map((s) => {
		const handler = () => {
			for (const t of signals) process.removeAllListeners(t);
			void stop(s);
		};
		process.once(s, handler);
		return handler;
	});
	try {
		const root = await harness.root(context, {
			agent: { model, thinkingLevel: options.thinking as ModelThinkingLevel, cwd },
		});
		out(
			reopened
				? `durable: resuming session ${options.session} from ${DIR}/${options.session}.sqlite (the prompt given now is not sent again)`
				: `durable: session ${options.session}, ${options.model}, thinking ${options.thinking}`,
		);
		const blocked = async () => {
			const inspection = await harness.inspect(context);
			const task = inspection.tasks.find((t) => t.state.kind === "blocked" && t.state.reason === "restart_limit");
			if (task) onParked(task.record.kind);
		};
		// The input with requestId, admitted once per session; then wait for its answer, or for a parked step
		const ask = async (requestId: string, content: string) => {
			const submission = await root.submit({ type: "input", content, requestId }, context);
			harness.resume();
			await blocked();
			return Promise.race([
				submission.wait(context).then((record) => ({ record, parked: undefined })),
				parked.then((kind) => ({ record: undefined, parked: kind })),
			]);
		};

		let result = await ask(FIRST, options.prompt);
		if (result.record?.status === "unanswered" && reopened) result = await ask(CONTINUE, CONTINUE_TEXT);
		if (result.record?.status === "done" && !existsSync(join(cwd, REPORT_FILE))) {
			result = await ask(REPORT, REPORT_TEXT);
		}
		await writeUsage(harness, dir, options.session);
		if (result.parked !== undefined) {
			parkedReport(cwd, options.restartLimit, result.parked);
			out(`durable: parked (restart_limit): ${result.parked} was cut short ${options.restartLimit} time(s) in a row; wrote ${REPORT_FILE} with ## Blocked`);
			return EXIT.parked;
		}
		const record = result.record!;
		if (record.status !== "done") {
			out(`durable: the model did not answer (${record.reason}${record.detail ? `: ${JSON.stringify(record.detail).slice(0, 300)}` : ""})`);
			return EXIT.failed;
		}
		const answer = await root.commit((tx) => tx.entry(AssistantEntry, record.answer!), context);
		const said = text(answer?.model?.[0]?.content).trim();
		if (said) out(said);
		return EXIT.answered;
	} finally {
		for (const [i, s] of signals.entries()) process.removeListener(s, handlers[i]);
		await harness.close(context);
	}
}

/** What the session used, for the comparison (tests/durable_bench.py): `.task-durable/<session>.usage.json`. */
async function writeUsage(harness: Harness, dir: string, session: string): Promise<void> {
	try {
		writeFileSync(join(dir, `${session}.usage.json`), `${JSON.stringify(await harness.usage(BACKGROUND_CONTEXT), null, 2)}\n`);
	} catch {
		// measuring never costs the run
	}
}
