export type Card = { id: string; title: string; status: string; repo: string; waitsFor: string }
export type Board = { counts: Record<string, number>; cards: Card[]; checkedAt: string; error: string }

declare module 'claude-code' {
  interface PluginState {
    'task-board': { board: Board | null }
  }
}
