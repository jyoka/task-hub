// What `task list` prints (bin/task cmd_list), with every column and a status it does not know.
export const LIST = `counts: Backlog=1, Ready=1, In progress=2, In review=1, wait for merge=1, Blocked=1
tasks[8]{id,title,status,repo,agent,waits_for}:
  "64","aica v1: Render 公開とデプロイ smoke(HITL)",Backlog,jyoka/aica,"",""
  "75",Test kiro automation workflow,In review,jyoka/task-hub,kiro,""
  "109","aica v2 (H): 完了時の計測",In progress,jyoka/aica,"",""
  "128",Claude Code 用のボード表示 mod,In progress › review,jyoka/task-hub,"",""
  "90",merge を待つカード,wait for merge,jyoka/task-hub,"",""
  "200",知らない列のカード,Someday,jyoka/task-hub,"",""
  "111",すぐ始められるカード,Ready,jyoka/task-hub,"",""
  "110","画面, 検索",Blocked,jyoka/aica,"","#109"
needs_you: 3 (Backlog to approve, In review, Blocked)
`
