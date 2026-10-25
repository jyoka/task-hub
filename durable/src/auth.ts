// pi's login, read only (task 191's spike, choice (a)): the runner reads the `openai-codex` credential that the pi CLI
// keeps in its auth.json and never writes it. A token close to its end is refreshed by pi-ai through `modify`, which
// this store refuses: the request then fails at once with `ModelsError` code `auth`, and the runner ends with the
// reason. Running `pi` once refreshes the token. Nothing here prints, copies, or logs a credential.
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { type CredentialStore, createModels, type Models, ModelsError } from "@earendil-works/pi-ai";
import { openaiCodexProvider } from "@earendil-works/pi-ai/providers/openai-codex";
import { readStoredCredential } from "@earendil-works/pi-coding-agent";

export const PROVIDER = "openai-codex";

/** pi's auth.json: in PI_CODING_AGENT_DIR when it is set, as for pi itself, else in ~/.pi/agent. */
export function defaultAuthPath(env: NodeJS.ProcessEnv = process.env): string {
	const dir = env.PI_CODING_AGENT_DIR?.trim();
	const agentDir = dir ? (dir === "~" ? homedir() : dir.startsWith("~/") ? join(homedir(), dir.slice(2)) : dir) : join(homedir(), ".pi", "agent");
	return join(agentDir, "auth.json");
}

/** Reads authPath again at each use, so a token the pi CLI refreshed meanwhile is the one used. */
export function readOnlyStore(authPath: string): CredentialStore {
	return {
		async read(providerId: string) {
			const credential = readStoredCredential(providerId, authPath);
			if (credential !== undefined || !existsSync(authPath)) return credential;
			// pi writes auth.json in place, not by a rename: one read in the middle of that finds no JSON. Once more
			await new Promise((resolve) => setTimeout(resolve, 250));
			return readStoredCredential(providerId, authPath);
		},
		async list() {
			const credential = readStoredCredential(PROVIDER, authPath);
			return credential ? [{ providerId: PROVIDER, type: credential.type }] : [];
		},
		async modify(providerId: string) {
			throw new Error(`read-only credential store: the runner does not write ${providerId}'s login; run pi once`);
		},
		async delete(providerId: string) {
			throw new Error(`read-only credential store: the runner does not delete ${providerId}'s login`);
		},
	} as CredentialStore;
}

export class AuthFailed extends Error {}

/** `openai-codex` models over pi's login. Throws AuthFailed, with a reason and no secret, when it cannot sign in. */
export async function connect(authPath: string): Promise<Models> {
	const models = createModels({ credentials: readOnlyStore(authPath) });
	models.setProvider(openaiCodexProvider());
	let auth: unknown;
	try {
		auth = await models.getAuth(PROVIDER);
	} catch (error) {
		if (error instanceof ModelsError && (error.code === "auth" || error.code === "oauth")) {
			throw new AuthFailed(`cannot sign in to ${PROVIDER} with the login in ${authPath} (ModelsError ${error.code}): ` +
				"it may have expired, and the runner never refreshes it. Run `pi` once, or log in again in pi");
		}
		throw error;
	}
	if (auth === undefined) {
		throw new AuthFailed(`no ${PROVIDER} login in ${authPath}: log in with pi (/login) first`);
	}
	return models;
}
