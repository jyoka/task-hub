//! task-rs: a local-first Rust copy of `task list`, `task list --watch` and `task events`, for comparing speed and
//! memory with bin/task. It reads the same local files (config.ini, board-cache.json, runs/, events.jsonl) and
//! prints the same lines. It calls GitHub only when the user asks (`task-rs sync`, `list --sync`), and then only
//! reads. Experimental: not part of task-hub, see rust/README.md.

use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::process::{self, Command};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use std::{env, fs, thread};

mod tui;

const VERSION: &str = "0.9.0";
const STATUSES: [&str; 7] = ["Backlog", "Ready", "In progress", "In review", "wait for merge", "Blocked", "Done"];
const NEEDS_USER: [&str; 3] = ["Backlog", "In review", "Blocked"];
const IN_PROGRESS: &str = "In progress";
const WATCH_SECONDS: u64 = 60;
const LIST_USAGE: &str = "task-rs list [--sync] [--watch]";
// bin/task's PROJECT_QUERY and ITEMS_QUERY: "@<field>" is replaced by the field's name as spelled on the board
const PROJECT_QUERY: &str = r#"query($owner: String!, $number: Int!) { repositoryOwner(login: $owner) { ... on ProjectV2Owner {
  projectV2(number: $number) { id url fields(first: 50) { nodes {
    ... on ProjectV2FieldCommon { id name dataType } ... on ProjectV2SingleSelectField { options { id name } } } } } } } }"#;
const ITEMS_QUERY: &str = r#"query($id: ID!, $q: String!, $after: String) { node(id: $id) { ... on ProjectV2 {
  items(first: 100, after: $after, query: $q) { pageInfo { hasNextPage endCursor } nodes { id updatedAt
    content { ... on Issue { number title url body state repository { nameWithOwner }
      blockedBy(first: 50) { nodes { number title state stateReason repository { nameWithOwner } } } } }
    status: fieldValueByName(name: "@Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    repo: fieldValueByName(name: "@Target repo") { ... on ProjectV2ItemFieldTextValue { text } }
    agent: fieldValueByName(name: "@Agent") { ... on ProjectV2ItemFieldTextValue { text } }
    base: fieldValueByName(name: "@Base branch") { ... on ProjectV2ItemFieldTextValue { text } } } } } } }"#;

// ---------- paths and output ----------

fn home_dir() -> String {
    env::var("HOME").unwrap_or_default()
}

fn state(name: &str) -> PathBuf {
    PathBuf::from(home_dir()).join(".local/state/task-hub").join(name)
}

fn tilde(p: &PathBuf) -> String {
    p.display().to_string().replace(&home_dir(), "~")
}

fn out(lines: &[String]) {
    println!("{}", lines.join("\n"));
}

fn fail(msg: &str, help: &str, code: i32) -> ! {
    println!("error: {msg}");
    if !help.is_empty() {
        println!("help: {help}");
    }
    process::exit(code)
}

fn now() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

fn is_word(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

fn is_number(s: &str) -> bool {
    // -?\d+(\.\d+)?
    let s = s.strip_prefix('-').unwrap_or(s);
    let (int, frac) = match s.split_once('.') {
        Some((i, f)) => (i, Some(f)),
        None => (s, None),
    };
    let digits = |p: &str| !p.is_empty() && p.chars().all(|c| c.is_ascii_digit());
    digits(int) && frac.map_or(true, digits)
}

/// bin/task's q(): a TOON value, quoted as JSON when it could be misread.
fn q(s: &str) -> String {
    if s.is_empty() || s != s.trim() || s.chars().any(|c| ",:\"\\[]{}\n#".contains(c))
        || matches!(s, "true" | "false" | "null") || is_number(s) {
        return serde_json::to_string(s).unwrap_or_default();
    }
    s.to_string()
}

// ---------- config ----------

/// The [board] project and issues of config.ini: just enough of configparser for that section.
fn board_config() -> (String, String, String) {
    let path = PathBuf::from(home_dir()).join(".config/task-hub/config.ini");
    let text = fs::read_to_string(&path).unwrap_or_default();
    let (mut section, mut project, mut issues) = (String::new(), String::new(), String::new());
    for line in text.trim_start_matches('\u{feff}').lines() {
        if line.starts_with(|c: char| c.is_whitespace()) {
            continue; // a continuation line of a multi-line value
        }
        let line = line.trim();
        if line.starts_with('[') && line.ends_with(']') {
            section = line[1..line.len() - 1].trim().to_string();
            continue;
        }
        if section != "board" || line.starts_with(';') || line.starts_with('#') {
            continue;
        }
        if let Some(at) = line.find(|c| c == '=' || c == ':') {
            let key = line[..at].trim().to_lowercase();
            let mut value = &line[at + 1..];
            for (i, c) in value.char_indices() { // inline comments need a space before them
                if (c == ';' || c == '#') && value[..i].ends_with(char::is_whitespace) {
                    value = &value[..i];
                    break;
                }
            }
            match key.as_str() {
                "project" => project = value.trim().to_string(),
                "issues" => issues = value.trim().to_string(),
                _ => {}
            }
        }
    }
    let name = |s: &str| !s.is_empty() && s.chars().all(|c| is_word(c) || c == '.' || c == '-');
    let ok_project = project.split_once('/').map_or(false, |(o, n)| name(o) && !n.is_empty()
        && n.chars().all(|c| c.is_ascii_digit()));
    let ok_issues = issues.split_once('/').map_or(false, |(o, r)| name(o) && name(r));
    if !ok_project || !ok_issues {
        fail(&format!("the board is not configured in {}", tilde(&path)),
             "add:  [board]  project = <owner>/<project number>  issues = <owner>/<issues repo>  (see docs/setup.md)", 1);
    }
    let (owner, number) = project.split_once('/').unwrap();
    (owner.to_string(), number.to_string(), issues)
}

// ---------- the board cache ----------

fn read_json(path: &PathBuf) -> Value {
    fs::read(path).ok().and_then(|b| serde_json::from_slice(&b).ok()).filter(Value::is_object)
        .unwrap_or(Value::Null)
}

fn read_number(path: &PathBuf) -> f64 {
    fs::read_to_string(path).ok().and_then(|s| s.trim().parse().ok()).unwrap_or(0.0)
}

fn ago(seconds: f64) -> String {
    let s = seconds.max(0.0) as u64;
    match s {
        0..=59 => format!("{s}s"),
        60..=3599 => format!("{}m", s / 60),
        3600..=86399 => format!("{}h", s / 3600),
        _ => format!("{}d", s / 86400),
    }
}

/// The open items of the local board (board-cache.json), at any age: GitHub is read only by `sync`.
fn local_items() -> Result<Vec<Value>, String> {
    let (items, age, changed) = load_local()?;
    let changed = if changed { ", task-hub changed the board since" } else { "" };
    eprintln!("board: local copy from {} ago{changed} (`task-rs sync` reads GitHub)", ago(age));
    Ok(items)
}

/// The local board's items, its age in seconds, and whether task-hub changed the board after it was read.
fn load_local() -> Result<(Vec<Value>, f64, bool), String> {
    let (owner, number, issues) = board_config();
    let mut data = read_json(&state("board-cache.json"));
    let (Some(at), Some(Value::Array(_))) = (data.get("fetched_at").and_then(Value::as_f64), data.get("items")) else {
        return Err("no local board yet: run `task-rs sync` to read it from GitHub".into());
    };
    if data.get("key") != Some(&serde_json::json!([owner, number, issues])) {
        return Err("the local board is of another board: run `task-rs sync`".into());
    }
    let changed = at <= read_number(&state("board-cache.stale"));
    match data["items"].take() {
        Value::Array(items) => Ok((items, now() - at, changed)),
        _ => unreachable!(),
    }
}

// ---------- sync: the only GitHub calls, and only when asked ----------

fn graphql(query: &str, vars: &[(&str, &str, bool)]) -> Result<Value, String> {
    let gh = env::var("TASK_GH").unwrap_or_else(|_| "gh".into());
    let mut cmd = Command::new(gh);
    cmd.args(["api", "graphql", "-f", &format!("query={query}")]);
    for (k, v, number) in vars { // -F sends an int as a number (an Int! variable)
        cmd.args([if *number { "-F" } else { "-f" }, &format!("{k}={v}")]);
    }
    let o = cmd.output().map_err(|e| format!("cannot run gh: {e}"))?;
    if !o.status.success() {
        let err = String::from_utf8_lossy(if o.stderr.is_empty() { &o.stdout } else { &o.stderr }).to_string();
        return Err(err.trim().lines().last().unwrap_or("gh failed").to_string());
    }
    let v: Value = serde_json::from_slice(&o.stdout).map_err(|e| format!("gh printed no JSON: {e}"))?;
    Ok(v["data"].clone())
}

/// The Project's id and the field names as spelled on the board: from board-meta.json (bin/task's), else GitHub.
fn project(owner: &str, number: &str, issues: &str) -> Result<(String, HashMap<String, String>), String> {
    let saved = read_json(&state("board-meta.json"));
    if saved.get("key") == Some(&serde_json::json!([owner, number, issues])) {
        if let (Some(id), Some(names)) = (saved["board"]["id"].as_str(), saved["board"]["names"].as_object()) {
            let names = names.iter().map(|(k, v)| (k.clone(), v.as_str().unwrap_or(k).to_string())).collect();
            return Ok((id.to_string(), names));
        }
    }
    let data = graphql(PROJECT_QUERY, &[("owner", owner, false), ("number", number, true)])?;
    let p = &data["repositoryOwner"]["projectV2"];
    let id = p["id"].as_str().ok_or(format!("cannot read GitHub Project {owner}/{number}"))?;
    let fields: HashMap<String, String> = p["fields"]["nodes"].as_array().into_iter().flatten()
        .filter_map(|f| f["name"].as_str()).map(|n| (n.to_lowercase(), n.to_string())).collect();
    let names = ["Status", "Target repo", "Agent", "Base branch"].iter()
        .map(|n| (n.to_string(), fields.get(&n.to_lowercase()).cloned().unwrap_or(n.to_string()))).collect();
    Ok((id.to_string(), names))
}

/// Reads the open cards from GitHub into board-cache.json, the same file bin/task writes and reads.
fn sync() -> Result<usize, String> {
    let (owner, number, issues) = board_config();
    let (id, names) = project(&owner, &number, &issues)?;
    let mut query = ITEMS_QUERY.to_string();
    for (n, spelled) in &names {
        query = query.replace(&format!("\"@{n}\""), &serde_json::to_string(spelled).unwrap());
    }
    let fetched_at = now(); // before the read: a board change during it makes this read stale
    let (mut items, mut after) = (vec![], String::new());
    loop {
        let mut vars = vec![("id", id.as_str(), false), ("q", "-status:Done", false)];
        if !after.is_empty() {
            vars.push(("after", after.as_str(), false));
        }
        let mut page = graphql(&query, &vars)?["node"]["items"].take();
        if let Value::Array(nodes) = page["nodes"].take() {
            items.extend(nodes);
        }
        match page["pageInfo"]["endCursor"].as_str() {
            Some(cursor) if page["pageInfo"]["hasNextPage"] == true => after = cursor.to_string(),
            _ => break,
        }
    }
    let n = items.len();
    if fetched_at > read_number(&state("board-cache.stale")) { // else bin/task would never use it
        let text = serde_json::json!({"key": [owner, number, issues], "fetched_at": fetched_at, "items": items});
        let (path, tmp) = (state("board-cache.json"), state("board-cache.json.rs-tmp"));
        fs::write(&tmp, text.to_string()).and_then(|_| fs::rename(&tmp, &path)).map_err(|e| e.to_string())?;
    }
    Ok(n)
}

fn cmd_sync() {
    let began = now();
    match sync() {
        Ok(n) => println!("synced: {n} open card(s) from GitHub in {:.1}s", now() - began),
        Err(e) => fail(&e, "check `gh auth status`; the local board is unchanged", 1),
    }
}

// ---------- tasks ----------

struct Blocker {
    reference: String,
    number: String,
    state: String,
    reason: String,
}

struct Task {
    id: String,
    url: String,
    pr: String,
    log: String,
    started: String,
    num: u64,
    title: String,
    updated: String,
    status: String,
    repo: String,
    agent: String,
    stage: String,
    running: bool,
    waits_for: String,
}

fn text(v: &Value, key: &str) -> String {
    v.get(key).and_then(Value::as_str).unwrap_or("").to_string()
}

fn canonical(status: &str) -> String {
    STATUSES.iter().find(|s| s.to_lowercase() == status.to_lowercase()).map(|s| s.to_string())
        .unwrap_or_else(|| if status.is_empty() { "Backlog".into() } else { status.into() })
}

/// Task numbers under a "Blocked by" or "Ready conditions" heading of the Issue body, in order.
fn mentioned_blockers(body: &str) -> Vec<String> {
    let mut found: Vec<String> = vec![];
    let mut inside = false;
    for line in body.lines() {
        let rest = line.trim_start();
        if rest.starts_with('#') && !rest[1..].starts_with(|c: char| c.is_ascii_digit()) {
            let heading = rest.trim_start_matches('#').trim_start().to_lowercase();
            inside = ["blocked by", "ready conditions"].iter().any(|h| heading.starts_with(h)
                && !heading[h.len()..].starts_with(is_word));
        } else if inside {
            let chars: Vec<char> = line.chars().collect();
            for i in 0..chars.len() {
                if chars[i] != '#' || (i > 0 && (is_word(chars[i - 1]) || chars[i - 1] == '/')) {
                    continue;
                }
                let digits: String = chars[i + 1..].iter().take_while(|c| c.is_ascii_digit()).collect();
                let next = chars.get(i + 1 + digits.len());
                if !digits.is_empty() && !next.map_or(false, |&c| is_word(c)) && !found.contains(&digits) {
                    found.push(digits);
                }
            }
        }
    }
    found
}

fn waiting_reason(b: &Blocker, statuses: &HashMap<String, String>) -> String {
    if b.state == "CLOSED" {
        return if b.reason == "NOT_PLANNED" || b.reason == "DUPLICATE" {
            format!("closed as {}", b.reason.to_lowercase().replace('_', " "))
        } else { String::new() };
    }
    if b.reference.starts_with('#') {
        return statuses.get(&b.number).cloned().unwrap_or_else(|| "open, not on the board".into());
    }
    "open".into()
}

/// Seconds since 1970 of "YYYY-MM-DDTHH:MM:SSZ".
fn epoch(stamp: &str) -> Option<f64> {
    let n = |a: usize, b: usize| stamp.get(a..b)?.parse::<i64>().ok();
    let (y, m, d) = (n(0, 4)?, n(5, 7)?, n(8, 10)?);
    let (hh, mm, ss) = (n(11, 13)?, n(14, 16)?, n(17, 19)?);
    let (y, m) = if m <= 2 { (y - 1, m + 12) } else { (y, m) }; // days from civil, March-based year
    let days = 365 * y + y / 4 - y / 100 + y / 400 + (153 * (m - 3) + 2) / 5 + d - 719469;
    Some((days * 86400 + hh * 3600 + mm * 60 + ss) as f64)
}

fn alive(id: &str, run: &Value) -> bool {
    let pid = match run.get("pid") {
        Some(Value::Number(n)) if n.as_i64() != Some(0) => n.to_string(),
        Some(Value::String(s)) if !s.is_empty() => s.clone(),
        _ => {
            // launched but `_run` has not recorded itself yet; give it two minutes
            return epoch(&text(run, "started")).map_or(false, |at| now() - at < 120.0);
        }
    };
    if cfg!(windows) {
        let _ = id;
        return false; // bin/task asks Windows for the command line; this prototype does not
    }
    Command::new("ps").args(["-p", &pid, "-o", "command="]).output()
        .map_or(false, |o| o.status.success() && String::from_utf8_lossy(&o.stdout).contains("_run"))
}

fn tasks(items: &[Value], issues: &str) -> Vec<Task> {
    let mut result = vec![];
    let mut extra: Vec<(Vec<Blocker>, Vec<String>)> = vec![];
    for item in items {
        let content = &item["content"];
        let Some(number) = content.get("number").and_then(Value::as_u64) else { continue };
        if content["repository"]["nameWithOwner"].as_str().unwrap_or("").to_lowercase() != issues.to_lowercase() {
            continue; // a PR, or an Issue from another repo
        }
        let value = |k: &str| {
            let f = &item[k];
            let name = text(f, "name");
            (if name.is_empty() { text(f, "text") } else { name }).trim().to_string()
        };
        let blockers = content["blockedBy"]["nodes"].as_array().map(|nodes| nodes.iter().filter(|n| n.is_object())
            .map(|n| {
                let repo = n["repository"]["nameWithOwner"].as_str().unwrap_or("");
                let num = n["number"].to_string();
                Blocker {
                    reference: if repo.to_lowercase() == issues.to_lowercase() { format!("#{num}") }
                               else { format!("{repo}#{num}") },
                    number: num,
                    state: text(n, "state"),
                    reason: text(n, "stateReason"),
                }
            }).collect()).unwrap_or_default();
        let id = number.to_string();
        let run = read_json(&state(&format!("runs/{id}.json")));
        result.push(Task {
            url: text(content, "url"),
            pr: text(&run, "pr"),
            log: text(&run, "log"),
            started: text(&run, "started"),
            running: alive(&id, &run),
            stage: text(&run, "stage"),
            title: text(content, "title"),
            updated: text(item, "updatedAt"),
            status: canonical(&value("status")),
            repo: value("repo"),
            agent: value("agent"),
            num: number,
            id,
            waits_for: String::new(),
        });
        extra.push((blockers, mentioned_blockers(content["body"].as_str().unwrap_or(""))));
    }
    let statuses: HashMap<String, String> = result.iter().map(|t| (t.id.clone(), t.status.clone())).collect();
    for (t, (blockers, mentioned)) in result.iter_mut().zip(extra) {
        let linked: HashSet<&str> = blockers.iter().filter(|b| b.reference.starts_with('#'))
            .map(|b| b.number.as_str()).collect();
        let mut waits: Vec<String> = blockers.iter().filter_map(|b| {
            let why = waiting_reason(b, &statuses);
            (!why.is_empty()).then(|| format!("{} ({why})", b.reference))
        }).collect();
        waits.extend(mentioned.iter().filter(|n| !linked.contains(n.as_str()) && **n != t.id)
            .filter_map(|n| statuses.get(n).map(|s| format!("#{n} ({s}, only in the body: link it)"))));
        if t.running && t.status != IN_PROGRESS {
            let stage = if t.stage.is_empty() { "starting" } else { &t.stage };
            waits.push(format!("its last run, still running ({stage})"));
        }
        t.waits_for = waits.join(", ");
    }
    // the card changed last first, as on the board
    result.sort_by(|a, b| (&b.updated, b.num).cmp(&(&a.updated, a.num)));
    result
}

fn shown_status(t: &Task) -> String {
    if t.running && !t.stage.is_empty() { format!("{} › {}", t.status, t.stage) } else { t.status.clone() }
}

fn list_lines(board: &[Task]) -> Vec<String> {
    let counts: Vec<(&str, usize)> = STATUSES.iter().filter(|s| **s != "Done")
        .map(|s| (*s, board.iter().filter(|t| t.status == *s).count())).collect();
    let mut lines = vec![format!("counts: {}",
        counts.iter().map(|(s, n)| format!("{s}={n}")).collect::<Vec<_>>().join(", "))];
    if board.is_empty() {
        lines.push("tasks: 0 open tasks".into());
    } else {
        lines.push(format!("tasks[{}]{{id,title,status,repo,agent,waits_for}}:", board.len()));
        for t in board {
            let row = [&t.id, &t.title, &shown_status(t), &t.repo, &t.agent, &t.waits_for];
            lines.push(format!("  {}", row.iter().map(|v| q(v)).collect::<Vec<_>>().join(",")));
        }
    }
    let needs: usize = counts.iter().filter(|(s, _)| NEEDS_USER.contains(s)).map(|(_, n)| n).sum();
    lines.push(format!("needs_you: {needs} (Backlog to approve, In review, Blocked)"));
    lines
}

fn read_board() -> Result<Vec<Task>, String> {
    let (_, _, issues) = board_config();
    Ok(tasks(&local_items()?, &issues))
}

fn local_now() -> String {
    Command::new("date").arg("+%Y-%m-%d %H:%M:%S %Z").output().ok()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default()
}

fn cmd_list(flags: &HashMap<String, String>) {
    if flags.contains_key("sync") {
        if let Err(e) = sync() {
            eprintln!("sync: {e}; showing the local board");
        }
    }
    if !flags.contains_key("watch") {
        match read_board() {
            Ok(board) => out(&list_lines(&board)),
            Err(e) => fail(&e, "", 1),
        }
        return;
    }
    let terminal = std::io::IsTerminal::is_terminal(&std::io::stdout());
    let mut last: Option<HashMap<String, String>> = None;
    loop {
        let lines = match read_board() {
            Ok(board) => {
                let mut lines = list_lines(&board);
                for (i, t) in board.iter().enumerate() {
                    if terminal && last.as_ref().map_or(false, |l| l.get(&t.id) != Some(&shown_status(t))) {
                        lines[i + 2] = format!("\x1b[1;33m{}\x1b[0m", lines[i + 2]);
                    }
                }
                last = Some(board.iter().map(|t| (t.id.clone(), shown_status(t))).collect());
                lines
            }
            Err(e) => vec![format!("error: {e}")],
        };
        let head = if terminal {
            format!("\x1b[H\x1b[2J== {} (every {WATCH_SECONDS}s, read only; Ctrl-C to stop)", local_now())
        } else {
            format!("== {}", local_now())
        };
        out(&[vec![head], lines].concat());
        if env::var_os("TASK_WATCH_ONCE").is_some() {
            return;
        }
        thread::sleep(Duration::from_secs(WATCH_SECONDS));
    }
}

// ---------- events ----------

fn shown(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

fn event_line(e: &Value) -> String {
    let mut parts = vec![format!("event: #{} {}", shown(&e["id"]), shown(&e["event"])), text(e, "title"), text(e, "repo")];
    for k in ["reason", "decision", "pr"] {
        match e.get(k) {
            None | Some(Value::Null) | Some(Value::Bool(false)) => {}
            Some(Value::String(s)) if s.is_empty() => {}
            Some(v) => parts.push(format!("{k} {}", shown(v))),
        }
    }
    parts.join(" | ")
}

fn cmd_events(flags: &HashMap<String, String>) {
    if flags.contains_key("digest") || flags.contains_key("follow") || flags.contains_key("next") {
        fail("--digest, --follow and --next are not in the Rust prototype", "use `task events`", 2);
    }
    let only: HashSet<String> = flags.get("only").map(|o| o.split(',').map(|e| e.trim().to_lowercase())
        .filter(|e| !e.is_empty()).collect()).unwrap_or_default();
    let path = state("events.jsonl");
    let text_ = fs::read_to_string(&path).unwrap_or_default();
    let lines: Vec<&str> = text_.lines().collect();
    let recent = &lines[lines.len().saturating_sub(20)..];
    let shown_lines: Vec<String> = recent.iter().filter(|l| l.starts_with('{'))
        .filter_map(|l| serde_json::from_str::<Value>(l).ok())
        .filter(|e| only.is_empty() || only.contains(&text(e, "event").to_lowercase()))
        .map(|e| event_line(&e)).collect();
    if shown_lines.is_empty() {
        out(&[format!("events: none yet in {}", tilde(&path))]);
    } else {
        out(&shown_lines);
    }
}

// ---------- main ----------

fn main() {
    let argv: Vec<String> = env::args().skip(1).collect();
    match argv.first().map(String::as_str) {
        Some("-v" | "-V" | "--version") => return println!("{VERSION}"),
        None | Some("-h" | "--help" | "help") => {
            return out(&["commands (read only, a Rust prototype of bin/task):".into(),
                         format!("  {LIST_USAGE}  # the open cards from the local board; --sync reads GitHub first"),
                         "  task-rs sync  # read the open cards from GitHub into the local board, once".into(),
                         "  task-rs events [--only \"In review,Blocked\"]  # the last 20 events".into(),
                         "  task-rs tui  # a live, read-only terminal view of the board, runs and events".into()]);
        }
        _ => {}
    }
    let (name, rest) = (argv[0].as_str(), &argv[1..]);
    let known: &[(&str, bool)] = match name {
        "list" => &[("watch", false), ("sync", false)],
        "sync" => &[],
        "tui" => &[],
        "events" => &[("only", true), ("digest", false), ("follow", false), ("next", false)],
        _ => fail(&format!("unknown command {}", serde_json::to_string(name).unwrap()), "commands: list, sync, events, tui", 2),
    };
    let mut flags = HashMap::new();
    let mut i = 0;
    while i < rest.len() {
        let Some(f) = rest[i].strip_prefix("--") else {
            fail(&format!("`{name}` takes no arguments, got {}", rest[i]), "", 2);
        };
        match known.iter().find(|(k, _)| *k == f) {
            None => fail(&format!("unknown flag {} for `{name}`", rest[i]), "", 2),
            Some((_, true)) => {
                let Some(v) = rest.get(i + 1) else { fail(&format!("{} needs a value", rest[i]), "", 2) };
                flags.insert(f.to_string(), v.clone());
                i += 1;
            }
            Some((_, false)) => {
                flags.insert(f.to_string(), String::new());
            }
        }
        i += 1;
    }
    match name {
        "list" => cmd_list(&flags),
        "sync" => cmd_sync(),
        "tui" => tui::run(),
        _ => cmd_events(&flags),
    }
}
