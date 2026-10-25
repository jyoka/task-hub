// npm test: the runner as task-hub starts it, a process in a git worktree, with pi-ai's faux provider in place of the
// model (test/faux-agent.ts), and dist/cli.js itself for the login. Each test has its own temporary worktree and
// never reads pi's real login (--auth points into the test's folder).
import assert from "node:assert/strict";
import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { defaultAuthPath } from "../dist/auth.js";
import { DIR, EXIT, MODEL, parseArgs, REPORT_FILE, step, THINKING } from "../dist/runner.js";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const FAUX = join(ROOT, "test", "faux-agent.ts");
const CLI = join(ROOT, "dist", "cli.js");
const DEADLINE_MS = 30_000; // for one start of the runner
const dirs: string[] = [];
const started: ChildProcess[] = [];

after(() => {
	for (const p of started) if (p.exitCode === null && p.signalCode === null) killGroup(p.pid!);
	for (const d of dirs) rmSync(d, { recursive: true, force: true });
});

function worktree(): string {
	const dir = mkdtempSync(join(tmpdir(), "durable-test-"));
	dirs.push(dir);
	spawnSync("git", ["init", "-q"], { cwd: dir });
	return dir;
}

type Ran = { code: number | null; out: string };

/** One start of program in cwd, in a process group of its own as task-hub starts an agent; ends within the deadline. */
function start(cwd: string, args: string[], env: Record<string, string> = {}, program = FAUX) {
	const child = spawn(process.execPath, ["--disable-warning=ExperimentalWarning", program, ...args], {
		cwd,
		env: { ...process.env, ...env },
		detached: true,
		stdio: ["ignore", "pipe", "pipe"],
	});
	started.push(child);
	let out = "";
	child.stdout!.on("data", (d) => (out += d));
	child.stderr!.on("data", (d) => (out += d));
	const ended = new Promise<Ran>((resolve, reject) => {
		const timer = setTimeout(() => {
			killGroup(child.pid!);
			reject(new Error(`no end within ${DEADLINE_MS} ms: ${out}`));
		}, DEADLINE_MS);
		child.on("close", (code) => {
			clearTimeout(timer);
			resolve({ code, out });
		});
	});
	return { child, ended, output: () => out };
}

function killGroup(pid: number): void {
	try {
		process.kill(-pid, "SIGKILL");
	} catch {
		// gone
	}
}

async function until(check: () => boolean, what: string): Promise<void> {
	const end = Date.now() + DEADLINE_MS;
	while (!check()) {
		if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
		await new Promise((r) => setTimeout(r, 50));
	}
}

function alive(pid: number): boolean {
	try {
		process.kill(pid, 0);
		return true;
	} catch {
		return false;
	}
}

const read = (cwd: string, file: string) => readFileSync(join(cwd, file), "utf8");
/** The process group of the bash call running now: scripts/group-shell's one file in .task-durable/s1.groups/. */
const groupOf = (cwd: string) => {
	const names = readdirSync(join(cwd, DIR, "s1.groups"));
	assert.equal(names.length, 1, String(names));
	return Number(names[0]);
};
const calls = (cwd: string) => read(cwd, "calls").trim().split("\n");

/** The first start, killed with its process group (kill -9) while its bash call sleeps. Returns the bash's group. */
async function killMidTool(cwd: string, extra: string[] = []): Promise<number> {
	const first = start(cwd, ["--session", "s1", ...extra, "Do it"], { FAUX_SLEEP: "60", FAUX_CALLS: join(cwd, "calls") });
	await until(() => existsSync(join(cwd, ".tool-started")), "the bash call to start");
	const bash = groupOf(cwd);
	assert.ok(alive(bash));
	killGroup(first.child.pid!);
	const ran = await first.ended;
	assert.equal(ran.code, null); // killed
	assert.ok(alive(bash), "Pi Durable's bash is in a group of its own: the runner's group kill misses it");
	return bash;
}

test("answers, shows each step, writes the report and what it used, and keeps .task-durable/ out of git", async () => {
	const cwd = worktree();
	const ran = await start(cwd, ["--session", "s1", "Do it"], { FAUX_CALLS: join(cwd, "calls") }).ended;
	assert.equal(ran.code, EXIT.answered, ran.out);
	assert.deepEqual(ran.out.trim().split("\n"), [
		"durable: session s1, faux/faux-1, thinking medium",
		"Running the slow step first.",
		"· bash: echo started > .tool-started && sleep 0 && echo finished > slow-done.txt",
		"Writing the report.",
		`· write: ${REPORT_FILE}`,
		"Done.",
	]);
	assert.match(read(cwd, REPORT_FILE), /bash: finished\. user inputs: 1\./);
	assert.deepEqual(calls(cwd), ["user", "toolResult bash", "toolResult write"]);
	const usage = JSON.parse(read(cwd, `${DIR}/s1.usage.json`));
	assert.ok(usage.models["faux/faux-1"], JSON.stringify(usage));
	assert.ok(!existsSync(join(cwd, DIR, "s1.lock")), "the lock is let go");
	assert.deepEqual(readdirSync(join(cwd, DIR, "s1.groups")), [], "a command that ended takes its group away");
	const status = spawnSync("git", ["status", "--porcelain", "--untracked-files=all"], { cwd, encoding: "utf8" }).stdout;
	assert.ok(!status.includes(DIR), status);
	assert.ok(status.includes(REPORT_FILE), status);
});

test("killed in the middle of a tool call, it goes on from there when started again: resume(), not the prompt again", async () => {
	const cwd = worktree();
	const bash = await killMidTool(cwd);
	assert.ok(existsSync(join(cwd, DIR, "s1.lock")), "kill -9 leaves the lock");
	const ran = await start(cwd, ["--session", "s1", "Do it\n\n# Resumed\n..."], { FAUX_CALLS: join(cwd, "calls") }).ended;
	assert.equal(ran.code, EXIT.answered, ran.out);
	const lines = ran.out.trim().split("\n");
	assert.equal(lines[0], `durable: stopped process group ${bash}, which a command of the run cut short left running`);
	assert.match(lines[1], /^durable: resuming session s1 from \.task-durable\/s1\.sqlite/);
	assert.ok(!lines.some((l) => l.startsWith("· bash")), "the cut-short call is not run again");
	assert.ok(!alive(bash), "what the killed run left was stopped");
	assert.ok(!existsSync(join(cwd, "slow-done.txt")), "the cut-short command never finished");
	// the model got the bash call's result as interrupted, and the conversation holds the first input only
	assert.match(read(cwd, REPORT_FILE), /bash: interrupted\. user inputs: 1\./);
	assert.deepEqual(calls(cwd), ["user", "toolResult bash", "toolResult write"]);
});

test("SIGTERM (task-hub stopping it, Ctrl-C): it closes, lets go of the lock, stops its command, and ends by the signal", async () => {
	const cwd = worktree();
	const run = start(cwd, ["--session", "s1", "Do it"], { FAUX_SLEEP: "60" });
	await until(() => existsSync(join(cwd, ".tool-started")), "the bash call to start");
	const bash = groupOf(cwd);
	run.child.kill("SIGTERM");
	await run.ended;
	assert.equal(run.child.signalCode, "SIGTERM", run.output());
	assert.match(run.output(), /durable: stopped by SIGTERM/);
	assert.ok(!existsSync(join(cwd, DIR, "s1.lock")));
	await until(() => !alive(bash), "its bash call to stop");
	// Pi Durable SIGKILLed the command with its group-shell, so the group's file stayed: the next start must not
	// stop that dead group id (task-hub resumes after SIGTERM and SIGHUP)
	assert.ok(existsSync(join(cwd, DIR, "s1.groups", String(bash))));
	const again = await start(cwd, ["--session", "s1", "Do it"]).ended;
	assert.equal(again.code, EXIT.answered, again.out);
	assert.ok(!again.out.includes("stopped process group"), again.out);
});

test("a group file left behind never stops a group that is not its group-shell any more (a dead id come back)", async () => {
	const cwd = worktree();
	// a process group of someone else's that now has the id of a group-shell the run SIGKILLed
	const other = spawn("sleep", ["30"], { detached: true, stdio: "ignore" });
	started.push(other);
	const groups = join(cwd, DIR, "s1.groups");
	mkdirSync(groups, { recursive: true });
	writeFileSync(join(groups, String(other.pid)), "Thu Jan  1 00:00:00 2026\n"); // the dead group-shell's start
	writeFileSync(join(groups, "999999"), ""); // and a group that is gone
	const ran = await start(cwd, ["--session", "s1", "Do it"]).ended;
	assert.equal(ran.code, EXIT.answered, ran.out);
	assert.ok(!ran.out.includes("stopped process group"), ran.out);
	assert.ok(alive(other.pid!), "the other process group lives on");
	assert.deepEqual(readdirSync(groups), [], "the files left behind are taken away");
	killGroup(other.pid!);
});

test("a session in use by a live process is left alone (exit 2); a dead owner's lock is taken over", async () => {
	const cwd = worktree();
	const holder = spawn("sleep", ["30"], { stdio: "ignore" });
	started.push(holder);
	const lock = join(cwd, DIR, "s1.lock");
	mkdirSync(join(cwd, DIR));
	writeFileSync(lock, `${holder.pid}\n`);
	const ran = await start(cwd, ["--session", "s1", "Do it"]).ended;
	assert.equal(ran.code, EXIT.locked, ran.out);
	assert.match(ran.out, new RegExp(`session s1 is in use by process ${holder.pid}`));
	assert.ok(!existsSync(join(cwd, DIR, "s1.sqlite")), "it did not open the storage");
	assert.equal(read(cwd, `${DIR}/s1.lock`), `${holder.pid}\n`);
	holder.kill("SIGKILL");
	await new Promise((r) => holder.on("close", r));
	const again = await start(cwd, ["--session", "s1", "Do it"]).ended;
	assert.equal(again.code, EXIT.answered, again.out);
	assert.ok(!existsSync(lock));
});

test("a step cut short restart_limit times is parked: a ## Blocked report and exit 3", async () => {
	const cwd = worktree();
	await killMidTool(cwd, ["--restart-limit", "1"]);
	const ran = await start(cwd, ["--session", "s1", "--restart-limit", "1", "Do it"], { FAUX_CALLS: join(cwd, "calls") }).ended;
	assert.equal(ran.code, EXIT.parked, ran.out);
	assert.match(ran.out, /durable: parked \(restart_limit\)/);
	const report = read(cwd, REPORT_FILE);
	assert.ok(report.startsWith("## Blocked\n\ndurable runner: restart_limit: "), report);
	assert.match(report, /\n## Report\n/);
	assert.deepEqual(calls(cwd), ["user"], "the parked step was not run again, nor the model asked");
	assert.ok(existsSync(join(cwd, DIR, "s1.usage.json")));
	assert.ok(!existsSync(join(cwd, DIR, "s1.lock")));
});

test("an answer without the report gets one request for it", async () => {
	const cwd = worktree();
	const ran = await start(cwd, ["--session", "s1", "Do it"], { FAUX_MODE: "noreport", FAUX_CALLS: join(cwd, "calls") }).ended;
	assert.equal(ran.code, EXIT.answered, ran.out);
	assert.match(read(cwd, REPORT_FILE), /bash: asked for the report\. user inputs: 2\./);
	assert.deepEqual(calls(cwd), ["user", "toolResult bash", "user", "toolResult write"]);
});

test("pi's login: none, or one that would need refreshing, ends with the reason (exit 1) and never writes it", async () => {
	const cwd = worktree();
	const auth = join(cwd, "auth.json");
	const none = await start(cwd, ["--session", "s1", "--auth", auth, "Do it"], {}, CLI).ended;
	assert.equal(none.code, EXIT.failed, none.out);
	assert.match(none.out, new RegExp(`durable: no openai-codex login in ${auth}`));
	// fake values: an OAuth login past its end, which pi-ai refreshes through the store's modify
	const fake = { "openai-codex": { type: "oauth", access: "FAKE-ACCESS", refresh: "FAKE-REFRESH", expires: Date.now() - 60_000, accountId: "fake" } };
	writeFileSync(auth, JSON.stringify(fake));
	const expired = await start(cwd, ["--session", "s1", "--auth", auth, "Do it"], {}, CLI).ended;
	assert.equal(expired.code, EXIT.failed, expired.out);
	assert.match(expired.out, /cannot sign in to openai-codex with the login in .*\(ModelsError auth\)/);
	assert.ok(!/FAKE-(ACCESS|REFRESH)/.test(none.out + expired.out), "no credential in the output");
	assert.deepEqual(JSON.parse(read(cwd, "auth.json")), fake, "the login is never written");
	assert.ok(!existsSync(join(cwd, DIR, "s1.sqlite")), "nothing started");
	assert.ok(!existsSync(join(cwd, DIR, "s1.lock")));
});

test("the arguments: the model and thinking given explicitly by default, and a session that is a file name", () => {
	const options = parseArgs(["--session", "abc-1", "a prompt"], {});
	assert.equal(typeof options, "object");
	assert.deepEqual(
		{ ...(options as object), authPath: undefined },
		{ session: "abc-1", prompt: "a prompt", model: MODEL, thinking: THINKING, restartLimit: 5, authPath: undefined },
	);
	assert.equal(MODEL, "openai-codex/gpt-6-luna");
	assert.equal(THINKING, "medium"); // pi's DEFAULT_THINKING_LEVEL (pi-coding-agent 1.4.0)
	assert.match(String(parseArgs(["--session", "../x", "p"], {})), /letters, digits/);
	assert.match(String(parseArgs(["p"], {})), /--session is required/);
	assert.match(String(parseArgs(["--session", "s", "p", "q"], {})), /one prompt/);
	assert.match(String(parseArgs(["--session", "s", "--thinking", "huge", "p"], {})), /--thinking huge/);
	assert.equal((parseArgs(["--session", "s", "--", "--not-an-option"], {}) as { prompt: string }).prompt, "--not-an-option");
	assert.equal(defaultAuthPath({ PI_CODING_AGENT_DIR: "/x/agent" }), "/x/agent/auth.json");
	assert.match(defaultAuthPath({}), /\/\.pi\/agent\/auth\.json$/);
	assert.equal(step("bash", { command: "npm test\nnpm run lint" }, "/w"), "bash: npm test ...");
	assert.equal(step("edit", { path: "/w/src/a.ts" }, "/w"), "edit: src/a.ts");
	assert.equal(step("read", {}, "/w"), "read");
});
