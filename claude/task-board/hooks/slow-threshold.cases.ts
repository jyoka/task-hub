// metrics.jsonl lines, and what bin/task slow_threshold(agent) answers for them as [limit, usual].
// board.test.tsx holds panel.ts slowThreshold to it, and tests/test_task.py holds bin/task to it: the part after
// `CASES =` must stay plain JSON.
export const CASES =
{
  "metrics": [
    "{\"agent\": \"fake\", \"seconds\": 60, \"status\": \"In review\"}",
    "{\"agent\": \"fake\", \"seconds\": 180, \"status\": \"In review\"}",
    "{\"agent\": \"fake\", \"seconds\": 120, \"status\": \"Blocked\", \"blocked_by\": \"agent\"}",
    "{\"agent\": \"fake\", \"seconds\": 0, \"status\": \"Blocked\", \"blocked_by\": \"start\"}",
    "{\"agent\": \"fake\", \"seconds\": 5, \"status\": \"Blocked\", \"blocked_by\": \"setup\"}",
    "{\"agent\": \"fake\", \"seconds\": 9999, \"sta",
    "",
    "{\"agent\": \"even\", \"seconds\": 2400, \"status\": \"In review\"}",
    "{\"agent\": \"even\", \"seconds\": 300, \"status\": \"In review\"}",
    "{\"agent\": \"even\", \"seconds\": 1200, \"status\": \"In review\"}",
    "{\"agent\": \"even\", \"seconds\": 600, \"status\": \"In review\"}",
    "{\"agent\": \"two\", \"seconds\": 600, \"status\": \"In review\"}",
    "{\"agent\": \"two\", \"seconds\": 900, \"status\": \"In review\"}",
    "{\"agent\": \"zero\", \"status\": \"Blocked\", \"blocked_by\": \"finish error\"}",
    "{\"agent\": \"zero\", \"seconds\": null, \"status\": \"In review\"}",
    "{\"agent\": \"zero\", \"seconds\": 700, \"status\": \"In review\"}",
    "{\"agent\": \"long\", \"seconds\": 1500, \"status\": \"In review\"}",
    "{\"agent\": \"long\", \"seconds\": 1800, \"status\": \"In review\"}",
    "{\"agent\": \"long\", \"seconds\": 2100.5, \"status\": \"In review\"}"
  ],
  "cases": {
    "fake": [
      900,
      120
    ],
    "even": [
      3600,
      1200
    ],
    "two": [
      1800,
      null
    ],
    "zero": [
      900,
      0
    ],
    "long": [
      5400,
      1800
    ],
    "nobody": [
      1800,
      null
    ]
  }
}
