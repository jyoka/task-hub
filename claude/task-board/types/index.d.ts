export type Card = { id: string; title: string; status: string; repo: string; agent: string; waitsFor: string }
export type Board = { counts: Record<string, number>; cards: Card[]; checkedAt: string; error: string }
// What the pane shows under a card, from events.jsonl and metrics.jsonl: a running card's seconds so far, its agent's
// usual and slow seconds (bin/task slow_threshold), an In review card's verdict and PR, a Blocked card's reason.
export type Detail = {
  elapsed?: number; usual?: number | null; limit?: number; verdict?: string; pr?: string; reason?: string
}
export type Details = Record<string, Detail>

declare module 'claude-code' {
  interface PluginState {
    'task-board': { board: Board | null; details: Details }
  }
}
