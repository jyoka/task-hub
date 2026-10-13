//! `task-rs tui`: a live, read-only view of the local board, the runs on this machine, and the events.
//! Two screens: the board, to choose a task, and the reader, its Issue, diff or log over the whole terminal.
//! It reads only local files and redraws when they change. GitHub is read only when the user presses `f`.
//! `g` lends the terminal to Lazygit in the selected task's worktree: Lazygit is not read only, the board is.

use super::{alive, ago, board_config, epoch, fail, fetch, fetched_line, load_local, now, read_json, shown_status, state, tasks, text,
            tilde, Task};
use ratatui::crossterm::event::{self, DisableBracketedPaste, DisableFocusChange, DisableMouseCapture, EnableMouseCapture, Event,
                                KeyCode, KeyEventKind, KeyModifiers, MouseEventKind};
use ratatui::crossterm::terminal::{enable_raw_mode, Clear as ClearScreen, ClearType, EnterAlternateScreen};
use ratatui::crossterm::execute;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style, Stylize};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, Clear, List, ListItem, ListState, Paragraph, Wrap};
use ratatui::backend::CrosstermBackend;
use ratatui::{DefaultTerminal, Frame, Terminal};
use serde_json::Value;
use std::collections::HashMap;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::time::{Duration, SystemTime};
use std::{env, fs, thread};

/// Columns in the order a person acts on them: what needs you first.
const ORDER: [&str; 7] = ["In review", "Blocked", "In progress", "Ready", "wait for merge", "Backlog", "Done"];
const KEYS: &str = "↑↓ jk task  ⏎ issue  d diff  l log  PgUp/PgDn details  b browser  o open  g lazygit  f fetch  q quit";
const LOG_TAIL: u64 = 1 << 20; // the log's last 1 MB, when the reader opens it and while it follows new output
const LOG_MAX: u64 = 4 << 20; // the most it grows to while the reader stays on older output
const WHEEL: isize = 3; // rows per notch of the mouse wheel
const SIDEWAYS: usize = 8; // columns per ← or → in the diff

fn color(status: &str) -> Color {
    match status {
        "In review" => Color::Green,
        "Blocked" => Color::Red,
        "In progress" => Color::Yellow,
        "Ready" => Color::Cyan,
        "wait for merge" => Color::Magenta,
        _ => Color::Gray,
    }
}

/// A short tag for the board's narrow status column; a running task shows its stage and time instead.
fn tag(t: &Task) -> String {
    if t.running {
        let stage = if t.stage.is_empty() { "starting" } else { &t.stage };
        return match epoch(&t.started) {
            Some(at) => format!("{stage} {}", ago(now() - at)),
            None => stage.to_string(),
        };
    }
    match t.status.as_str() {
        "In review" => "review",
        "Blocked" => "blocked",
        "In progress" => "running",
        "wait for merge" => "merge",
        other => return other.to_lowercase(),
    }.to_string()
}

fn mtime(path: &PathBuf) -> Option<SystemTime> {
    fs::metadata(path).and_then(|m| m.modified()).ok()
}

/// The machine's offset from UTC in seconds, asked once (`date +%z`): std has no time zones.
fn utc_offset() -> i64 {
    let out = Command::new("date").arg("+%z").output().ok();
    let z = out.map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default();
    let (sign, digits) = match z.split_at_checked(1) {
        Some(("-", d)) => (-1, d),
        Some((_, d)) => (1, d),
        None => return 0,
    };
    let n = |r: std::ops::Range<usize>| digits.get(r).and_then(|d| d.parse::<i64>().ok()).unwrap_or(0);
    sign * (n(0..2) * 3600 + n(2..4) * 60)
}

/// "13:09" today, "10-09 13:09" before, in local time.
fn local_time(stamp: &str, offset: i64) -> String {
    let Some(at) = epoch(stamp) else { return String::new() };
    let local = |t: f64| t as i64 + offset;
    let (day, today) = (local(at).div_euclid(86400), local(now()).div_euclid(86400));
    let secs = local(at).rem_euclid(86400);
    let hm = format!("{:02}:{:02}", secs / 3600, secs % 3600 / 60);
    if day == today {
        return hm;
    }
    // civil from days (Howard Hinnant's algorithm)
    let z = day + 719468;
    let doe = z.rem_euclid(146097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let (d, m) = (doy - (153 * mp + 2) / 5 + 1, if mp < 10 { mp + 3 } else { mp - 9 });
    format!("{m:02}-{d:02} {hm}")
}

/// The log's size and time: the reader reads it again when they change.
fn log_stamp(path: &str) -> Option<(u64, Option<SystemTime>)> {
    fs::metadata(path).ok().map(|m| (m.len(), m.modified().ok()))
}

/// A run's log from byte `from` to its end, without the terminal's color codes; from its last LOG_TAIL bytes when
/// `from` is None or no longer fits. Returns the lines and where they start: a reader kept on older output reads
/// from the same place again, so that new output only adds lines at the bottom.
fn log_lines(path: &str, from: Option<u64>) -> (Vec<String>, u64) {
    let Ok(mut f) = fs::File::open(path) else { return (vec![format!("no log at {path}")], 0) };
    let len = f.metadata().map(|m| m.len()).unwrap_or(0);
    let start = match from {
        Some(at) if at <= len && len - at <= LOG_MAX => at,
        _ => len.saturating_sub(LOG_TAIL),
    };
    let _ = f.seek(SeekFrom::Start(start));
    let mut bytes = vec![];
    let _ = f.read_to_end(&mut bytes);
    let mut clean = String::new();
    let mut chars = String::from_utf8_lossy(&bytes).into_owned().chars().collect::<Vec<_>>().into_iter().peekable();
    while let Some(c) = chars.next() {
        match c {
            '\x1b' => { // CSI: ESC [ ... final letter; other escapes: drop the next char
                if chars.peek() == Some(&'[') {
                    chars.next();
                    while let Some(c) = chars.next() {
                        if c.is_ascii_alphabetic() || c == '~' {
                            break;
                        }
                    }
                } else {
                    chars.next();
                }
            }
            '\r' => {}
            '\t' => clean.push_str("    "),
            c if c.is_control() && c != '\n' => {}
            c => clean.push(c),
        }
    }
    // a start in the middle of the file cuts its first line
    let text = match clean.split_once('\n') {
        Some((_, rest)) if start > 0 && !rest.is_empty() => rest,
        _ => &clean, // unless it is all there is
    };
    (text.lines().map(str::to_string).collect(), start)
}

fn open_url(url: &str) -> String {
    if url.is_empty() {
        return "nothing to open".into();
    }
    let mut cmd = if cfg!(target_os = "macos") {
        Command::new("open")
    } else if cfg!(windows) {
        let mut c = Command::new("cmd");
        c.args(["/C", "start", ""]);
        c
    } else {
        Command::new("xdg-open")
    };
    match cmd.arg(url).stdout(Stdio::null()).stderr(Stdio::null()).spawn() {
        Ok(_) => format!("opened {url}"),
        Err(e) => format!("cannot open {url}: {e}"),
    }
}

/// What the reader shows of its task, over the whole screen.
#[derive(Clone, Copy, PartialEq)]
enum View {
    Issue,
    Diff,
    Log,
}

impl View {
    fn name(self) -> &'static str {
        match self {
            View::Issue => "Issue",
            View::Diff => "Diff",
            View::Log => "Log",
        }
    }

    /// The diff keeps its columns (←→ scroll it); the Issue and the log wrap.
    fn wraps(self) -> bool {
        self != View::Diff
    }
}

/// Where the reader is in a view: its top row on screen, its first column (the diff), and whether it follows new
/// output (the log, while it is at the bottom).
#[derive(Clone, Copy, Default)]
struct Pos {
    top: usize,
    left: usize,
    follow: bool,
    width: u16, // the width `top` was counted at
}

/// Rows on screen of each line at this width: a wrapped line wider than the screen takes more than one.
fn screen_rows(lines: &[Line<'static>], width: u16, wrap: bool) -> Vec<usize> {
    lines.iter().map(|l| {
        if !wrap || l.width() <= width as usize {
            1
        } else {
            Paragraph::new(l.clone()).wrap(Wrap { trim: false }).line_count(width).max(1)
        }
    }).collect()
}

/// The line that holds screen row `top`, and how many of its rows are above it.
fn locate(rows: &[usize], top: usize) -> (usize, usize) {
    let (mut line, mut skip) = (0, top);
    while line < rows.len() && skip >= rows[line] {
        skip -= rows[line];
        line += 1;
    }
    (line, skip)
}

/// The same place in lines wrapped at another width: the line that was at the top, as far into it.
fn same_place(old: &[usize], new: &[usize], top: usize) -> usize {
    let (line, skip) = locate(old, top);
    let within = match (old.get(line), new.get(line)) {
        (Some(&o), Some(&n)) => (skip * n / o.max(1)).min(n.saturating_sub(1)),
        _ => 0,
    };
    new.iter().take(line).sum::<usize>() + within
}

/// Draws the lines that fit in area from screen row `top` and, unwrapped, from column `left`. Only those lines are
/// laid out, from the line that holds the top row.
fn draw_rows(f: &mut Frame, area: Rect, lines: &[Line<'static>], rows: &[usize], wrap: bool, top: usize, left: usize) {
    let (first, skip) = locate(rows, top);
    let (mut last, mut shown) = (first, 0);
    while last < lines.len() && shown < skip + area.height as usize {
        shown += rows[last];
        last += 1;
    }
    let p = Paragraph::new(Text::from(lines[first..last].to_vec()));
    let at = |n: usize| n.min(u16::MAX as usize) as u16;
    f.render_widget(if wrap { p.wrap(Wrap { trim: false }).scroll((at(skip), 0)) } else { p.scroll((0, at(left))) }, area);
}

fn git(wt: &str, args: &[&str]) -> String {
    git_with(wt, args, None).unwrap_or_default()
}

/// git in the worktree, on another index file when one is given; None when it fails.
fn git_with(wt: &str, args: &[&str], index: Option<&Path>) -> Option<String> {
    let mut cmd = Command::new("git");
    cmd.arg("-C").arg(wt).args(args).stdin(Stdio::null());
    if let Some(index) = index {
        cmd.env("GIT_INDEX_FILE", index);
    }
    cmd.output().ok().filter(|o| o.status.success()).map(|o| String::from_utf8_lossy(&o.stdout).into_owned())
}

/// A copy of an index file in the temporary directory, made as a new file: never through a link someone left there.
fn index_copy(index: &Path) -> Option<PathBuf> {
    let mut from = fs::File::open(index).ok()?;
    let nanos = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).map_or(0, |d| d.subsec_nanos());
    let copy = std::env::temp_dir().join(format!("task-rs-{}-{nanos}.index", std::process::id()));
    let mut to = fs::OpenOptions::new().write(true).create_new(true).open(&copy).ok()?;
    if std::io::copy(&mut from, &mut to).is_err() {
        let _ = fs::remove_file(&copy);
        return None;
    }
    Some(copy)
}

/// What the agent changed in the task's worktree since it left its base, committed or not. Reads only: unlike
/// bin/task's staged_diff, it never runs `git add`.
fn diff_lines(t: &Task) -> Vec<Line<'static>> {
    if t.worktree.is_empty() || !PathBuf::from(&t.worktree).is_dir() {
        return vec![Line::from("no worktree for this task on this machine"), Line::default(),
                    Line::from("task-hub makes one when the task runs here and removes it when the task is Done.").dim()];
    }
    let wt = t.worktree.as_str();
    let base = if t.base.is_empty() {
        Some(git(wt, &["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).trim().to_string())
            .filter(|b| !b.is_empty()).unwrap_or_else(|| "origin/main".into())
    } else {
        format!("origin/{}", t.base)
    };
    let fork = Some(git(wt, &["merge-base", &base, "HEAD"]).trim().to_string())
        .filter(|f| !f.is_empty()).unwrap_or_else(|| "HEAD".into());
    let short: String = fork.chars().take(7).collect();
    // git diff refreshes the file times in the index and writes it back, under index.lock, where a running agent's
    // own git add or commit could fail: it reads a copy of the index (the index itself when no copy can be made)
    let index = git(wt, &["rev-parse", "--path-format=absolute", "--git-path", "index"]);
    let copy = index_copy(Path::new(index.trim()));
    let copied = copy.as_deref();
    let read = |args: &[&str]| git_with(wt, args, copied).or_else(|| git_with(wt, args, None)).unwrap_or_default();
    let mut lines = vec![Line::from(format!("changes since {base} ({short}) in {}", tilde(&PathBuf::from(wt)))).dim()];
    lines.extend(read(&["diff", "--stat", &fork, "--"]).lines().map(|l| Line::from(l.to_string())));
    let untracked = read(&["ls-files", "--others", "--exclude-standard"]);
    let new: Vec<&str> = untracked.lines().filter(|f| !f.starts_with(".task-")).collect();
    lines.extend(new.iter().map(|f| Line::from(format!(" new, not added yet: {f}")).yellow()));
    lines.push(Line::default());
    let diff = read(&["diff", &fork, "--"]);
    if let Some(copy) = copied {
        let _ = fs::remove_file(copy);
    }
    if diff.trim().is_empty() && new.is_empty() {
        lines.push(Line::from("no changes").dim());
    }
    for l in diff.lines() {
        let style = if l.starts_with("diff --git") {
            Style::new().yellow().bold()
        } else if l.starts_with("@@") {
            Style::new().cyan()
        } else if l.starts_with("+++") || l.starts_with("---") || l.starts_with("index ") {
            Style::new().dim()
        } else if l.starts_with('+') {
            Style::new().green()
        } else if l.starts_with('-') {
            Style::new().red()
        } else {
            Style::new()
        };
        lines.push(Line::styled(l.replace('\t', "    "), style));
    }
    lines
}

/// Where `g` would open Lazygit: the worktree that task-hub recorded for the task, read again from runs/<id>.json.
struct Target {
    id: String,
    repo: String,
    branch: String,
    worktree: PathBuf,
    running: Option<String>, // the stage of the agent running in it, if one is
}

/// The task's own worktree, or why Lazygit is not opened. Never another checkout: no fallback to the repository.
fn lazygit_target(id: &str) -> Result<Target, String> {
    let run = read_json(&state(&format!("runs/{id}.json")));
    let wt = text(&run, "worktree");
    if wt.is_empty() {
        return Err(format!("no worktree recorded for #{id} on this machine: Lazygit not opened"));
    }
    let worktree = PathBuf::from(&wt);
    if !worktree.is_dir() {
        return Err(format!("the worktree of #{id} is gone ({}): task-hub removes it when the task is Done. \
                            Lazygit not opened", tilde(&worktree)));
    }
    let top = git(&wt, &["rev-parse", "--show-toplevel"]);
    let same = |a: &Path, b: &Path| matches!((a.canonicalize(), b.canonicalize()), (Ok(a), Ok(b)) if a == b);
    if top.trim().is_empty() {
        return Err(format!("{} is not a Git worktree: Lazygit not opened", tilde(&worktree)));
    }
    if !same(Path::new(top.trim()), &worktree) {
        return Err(format!("{} is inside another checkout ({}), not the task's own worktree: Lazygit not opened",
                           tilde(&worktree), tilde(&PathBuf::from(top.trim()))));
    }
    // task-hub makes its worktrees with `git worktree add`: a main checkout (a clone) is never the task's
    let dirs = git(&wt, &["rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"]);
    let dirs: Vec<&str> = dirs.lines().collect();
    if dirs.len() != 2 || same(Path::new(dirs[0]), Path::new(dirs[1])) {
        return Err(format!("{} is a main checkout, not a task worktree: Lazygit not opened", tilde(&worktree)));
    }
    let branch = git(&wt, &["rev-parse", "--abbrev-ref", "HEAD"]).trim().to_string();
    let stage = text(&run, "stage");
    let running = alive(id, &run).then(|| if stage.is_empty() { "starting".into() } else { stage });
    Ok(Target { id: id.into(), repo: text(&run, "repo"), branch, worktree, running })
}

/// `lazygit` on PATH, found before the screen is handed over. Only absolute directories: a relative one would be
/// looked up in the worktree, where the agent writes.
fn lazygit_path() -> Option<PathBuf> {
    let name = if cfg!(windows) { "lazygit.exe" } else { "lazygit" };
    std::env::split_paths(&std::env::var_os("PATH")?).filter(|d| d.is_absolute()).map(|d| d.join(name))
        .find(|p| executable(p))
}

#[cfg(unix)]
fn executable(p: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    fs::metadata(p).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
}

#[cfg(not(unix))]
fn executable(p: &Path) -> bool {
    p.is_file()
}

/// The confirmation shown before Lazygit opens: which task, where, and what Lazygit can do there.
fn handoff_lines(t: &Target, title: &str) -> Vec<Line<'static>> {
    let field = |k: &str, v: String| Line::from(vec![Span::styled(format!("{k:<9}"), Style::new().dim()), v.into()]);
    let mut lines = vec![
        field("task", format!("#{} {title}", t.id)),
        field("repo", if t.repo.is_empty() { "-".into() } else { t.repo.clone() }),
        field("branch", if t.branch.is_empty() { "-".into() } else { t.branch.clone() }),
        field("worktree", tilde(&t.worktree)),
        Line::default(),
    ];
    if let Some(stage) = &t.running {
        lines.push(Line::from(format!("An agent is running in this worktree ({stage}). Inspect only: staging, committing, \
                                       reset, checkout and rebase can interfere with it.")).bold().yellow());
        lines.push(Line::default());
    }
    lines.extend([
        Line::from("The board stays read only. Lazygit is not: it can stage, commit, reset, check out, rebase and push. \
                    This note does not stop it."),
        Line::default(),
        Line::from("Lazygit lists uncommitted files only; d shows all the task changed since its base.").dim(),
        Line::default(),
        Line::from("Quit Lazygit to come back to the board."),
    ]);
    lines
}

/// The Issue (its Goal) from the local copy of the board: no browser, no network.
fn issue_lines(t: &Task, age: f64) -> Vec<Line<'static>> {
    let mut lines = vec![
        Line::from(format!("#{} {}", t.id, t.title)).bold(),
        Line::from(format!("{} (local copy from {} ago)", t.url, ago(age))).dim(),
        Line::default(),
    ];
    if t.body.trim().is_empty() {
        lines.push(Line::from("no body").dim());
    }
    let mut code = false;
    for l in t.body.lines() {
        let l = l.replace('\t', "    ");
        if l.trim_start().starts_with("```") {
            code = !code;
            lines.push(Line::from(l).dim());
        } else if code {
            lines.push(Line::from(l).dim());
        } else if l.starts_with('#') {
            lines.push(Line::from(l.trim_start_matches('#').trim().to_string()).bold().cyan());
        } else {
            lines.push(Line::from(l));
        }
    }
    lines
}

/// The full-screen reader: one task's Issue, diff or log. It stays on the task it opened on, by id: the arrows scroll
/// it, and a task that leaves the local board stays shown from its last copy, never replaced by another.
struct Reader {
    task: Task, // as last seen on the local board
    gone: bool, // the task is no longer on the local board
    view: View,
    pos: [Pos; 3], // each view's place, kept when switching between them, on reloads and across Lazygit
    lines: Vec<Line<'static>>,
    rows: Option<(u16, Vec<usize>, usize)>, // screen rows of each line at a width, and the widest line
    stale: bool,                            // the lines changed since: rows are of the ones before
    log_path: String,                       // the log file read last
    log_from: u64,                          // where its lines start in it
    log_seen: Option<(u64, Option<SystemTime>)>,
    page: usize,   // the body's height at the last draw
    bottom: usize, // the last top row that still fills the body, at the last draw
    right: usize,  // the last first column (the diff), at the last draw
    size: (u16, u16), // the body's width and height at the last draw
}

impl Reader {
    fn new(task: Task, view: View) -> Self {
        let log = Pos { follow: true, ..Pos::default() }; // the log opens at its end
        Reader { task, gone: false, view, pos: [Pos::default(), Pos::default(), log], lines: vec![], rows: None, stale: true,
                 log_path: String::new(), log_from: 0, log_seen: None, page: 1, bottom: 0, right: 0, size: (0, 0) }
    }

    /// Makes the view's lines again from the task as it is now: the local Issue, the worktree, the log file.
    fn fill(&mut self, age: f64) {
        let t = &self.task;
        self.lines = match self.view {
            View::Issue => issue_lines(t, age),
            View::Diff => diff_lines(t),
            View::Log if t.log.is_empty() => vec![Line::from("no run of this task on this machine").dim()],
            View::Log => {
                // another log file than the one read last starts again from its end
                let from = (!self.pos[View::Log as usize].follow && self.log_path == t.log).then_some(self.log_from);
                let (lines, start) = log_lines(&t.log, from);
                if from.is_some_and(|at| at != start) {
                    // it grew past LOG_MAX, or was cut or replaced: what was on screen is not there, go to the end
                    self.pos[View::Log as usize].follow = true;
                }
                (self.log_path, self.log_from, self.log_seen) = (t.log.clone(), start, log_stamp(&t.log));
                lines.into_iter().map(Line::from).collect()
            }
        };
        self.stale = true;
    }

    fn switch(&mut self, view: View, age: f64) {
        if self.view != view {
            self.view = view;
            self.rows = None;
            self.fill(age);
        }
    }

    /// Moves `by` rows. The log follows new output while it is at the bottom, and only then.
    fn scroll(&mut self, by: isize) {
        let (bottom, log) = (self.bottom, self.view == View::Log);
        let p = &mut self.pos[self.view as usize];
        p.top = p.top.saturating_add_signed(by).min(bottom);
        p.follow = log && p.top >= bottom;
    }

    fn sideways(&mut self, by: isize) {
        let right = self.right;
        let p = &mut self.pos[self.view as usize];
        p.left = p.left.saturating_add_signed(by).min(right);
    }

    fn key(&mut self, code: KeyCode, age: f64) {
        let page = self.page as isize;
        match code {
            KeyCode::Down | KeyCode::Char('j') => self.scroll(1),
            KeyCode::Up | KeyCode::Char('k') => self.scroll(-1),
            KeyCode::PageDown | KeyCode::Char(' ') => self.scroll(page),
            KeyCode::PageUp => self.scroll(-page),
            KeyCode::Home => {
                self.pos[self.view as usize].left = 0;
                self.scroll(isize::MIN);
            }
            KeyCode::End => self.scroll(isize::MAX),
            KeyCode::Right => self.sideways(SIDEWAYS as isize),
            KeyCode::Left => self.sideways(-(SIDEWAYS as isize)),
            KeyCode::Enter => self.switch(View::Issue, age),
            KeyCode::Char('d') => self.switch(View::Diff, age),
            KeyCode::Char('l') => self.switch(View::Log, age),
            _ => {}
        }
    }

    fn draw(&mut self, f: &mut Frame, head: Rect, body: Rect) {
        let (width, height, wrap) = (body.width, body.height as usize, self.view.wraps());
        let p = &mut self.pos[self.view as usize];
        // a new size keeps the reader at the end when it was there, else on the line it showed at the top
        let resized = (width, body.height) != self.size;
        let at_end = resized && self.bottom > 0 && p.top >= self.bottom;
        if self.stale || self.rows.as_ref().map_or(true, |(w, _, _)| *w != width) {
            let rows = screen_rows(&self.lines, width, wrap);
            if p.width != 0 && p.width != width {
                // its rows at the width it was last shown at: kept, or counted again after a switch
                p.top = match &self.rows {
                    Some((w, old, _)) if *w == p.width => same_place(old, &rows, p.top),
                    _ => same_place(&screen_rows(&self.lines, p.width, wrap), &rows, p.top),
                };
            }
            let widest = if wrap { 0 } else { self.lines.iter().map(Line::width).max().unwrap_or(0) };
            (self.rows, self.stale) = (Some((width, rows, widest)), false);
        }
        let Some((_, rows, widest)) = &self.rows else { return };
        let total: usize = rows.iter().sum();
        // kept within the text: it may have shrunk, or the terminal may have changed size
        (self.page, self.bottom) = (height.max(1), total.saturating_sub(height));
        self.right = widest.saturating_sub(width as usize);
        self.size = (width, body.height);
        p.top = if p.follow || at_end { self.bottom } else { p.top.min(self.bottom) };
        p.follow = self.view == View::Log && p.top >= self.bottom; // at the bottom, however it got there
        p.left = p.left.min(self.right);
        p.width = width;
        let p = *p;

        let mut right = vec![];
        if self.gone {
            right.push(" no longer on the local board (Done?) ".bold().yellow());
        }
        right.push(match total {
            0 => " empty ".dim(),
            _ => format!(" {}-{} of {} ", p.top + 1, (p.top + height).min(total), total).dim(),
        });
        if self.view == View::Log {
            right.push(if p.follow { " following ".green() } else { " paused, End follows ".yellow() });
        }
        if self.right > 0 {
            right.push(format!(" col {} of {} ", p.left + 1, widest).dim());
        }
        let right = Line::from(right);
        let [left, right_area] = Layout::horizontal([Constraint::Min(0), Constraint::Length(right.width() as u16)])
            .areas(head);
        let title = format!(" #{} {}", self.task.id, self.task.title);
        f.render_widget(Line::from(vec![format!(" {} ", self.view.name()).bold().reversed(), title.bold()]), left);
        f.render_widget(right, right_area);
        draw_rows(f, body, &self.lines, rows, wrap, p.top, p.left);
    }
}

struct App {
    board: Vec<Task>,
    age: f64,
    changed: bool,
    error: String,
    events: Vec<Value>,
    selected: ListState,
    details: usize,         // the details pane's top row
    details_page: usize,    // its height at the last draw
    reader: Option<Reader>, // None: the overview (the board, the details, the events)
    status: String,
    alert: bool, // the status is a Lazygit failure: shown in yellow until the next key
    offset: i64,
    seen: (Option<SystemTime>, Option<SystemTime>, Option<SystemTime>),
    loaded_at: f64,
    fetching: Option<Receiver<Result<(usize, bool), String>>>,
    confirm: Option<(Target, String)>, // `g` asks first: the target and the card's title
    launch: Option<String>,            // the task whose worktree main_loop hands the terminal to Lazygit in
    quit: bool,
}

impl App {
    fn new() -> Self {
        let mut app = App {
            board: vec![], age: 0.0, changed: false, error: String::new(), events: vec![],
            selected: ListState::default(), details: 0, details_page: 1, reader: None,
            status: "read only: GitHub is read only when you press f".into(), alert: false,
            offset: utc_offset(), seen: (None, None, None), loaded_at: 0.0, fetching: None, confirm: None, launch: None,
            quit: false,
        };
        app.reload();
        app
    }

    fn files() -> (Option<SystemTime>, Option<SystemTime>, Option<SystemTime>) {
        (mtime(&state("board-cache.json")), mtime(&state("events.jsonl")), mtime(&state("runs")))
    }

    /// Reads the board, the runs and the events again, keeping the selected card, and the reader's task and place.
    fn reload(&mut self) {
        let keep = self.current().map(|t| t.id.clone());
        let (_, _, issues) = board_config();
        match load_local() {
            Ok((items, age, changed)) => {
                let mut board = tasks(&items, &issues);
                board.sort_by_key(|t| ORDER.iter().position(|s| *s == t.status).unwrap_or(ORDER.len()));
                (self.board, self.age, self.changed, self.error) = (board, age, changed, String::new());
            }
            Err(e) => self.error = e,
        }
        let text_ = fs::read_to_string(state("events.jsonl")).unwrap_or_default();
        let lines: Vec<&str> = text_.lines().collect();
        self.events = lines[lines.len().saturating_sub(300)..].iter()
            .filter_map(|l| serde_json::from_str::<Value>(l).ok()).collect();
        let at = keep.and_then(|id| self.board.iter().position(|t| t.id == id))
            .or(if self.board.is_empty() { None } else { Some(0) });
        self.selected.select(at.map(|i| i.min(self.board.len().saturating_sub(1))));
        self.seen = Self::files();
        self.loaded_at = now();
        if let Some(r) = &mut self.reader {
            match self.board.iter().find(|t| t.id == r.task.id) {
                Some(t) => (r.task, r.gone) = (t.clone(), false),
                None => r.gone = true,
            }
            r.fill(self.age); // made again, from the worktree and the log as they are now
        }
    }

    fn current(&self) -> Option<&Task> {
        self.selected.selected().and_then(|i| self.board.get(i))
    }

    /// The task the keys act on: the reader's, or the selected card.
    fn focused(&self) -> Option<&Task> {
        match &self.reader {
            Some(r) => Some(&r.task),
            None => self.current(),
        }
    }

    /// The newest event of a task, and its newest event that carries a digest.
    fn last_events(&self, id: &str) -> (Option<&Value>, Option<&Value>) {
        let mine = self.events.iter().rev().filter(|e| super::shown(&e["id"]) == id);
        let last = mine.clone().next();
        (last, mine.into_iter().find(|e| e["digest"].is_object()))
    }

    fn tick(&mut self) {
        if let Some(rx) = &self.fetching {
            if let Ok(result) = rx.try_recv() {
                self.status = fetched_line(&result);
                self.fetching = None;
                self.reload();
                return;
            }
        }
        // files changed, or every 15s for the elapsed times and runs that ended
        if Self::files() != self.seen || now() - self.loaded_at >= 15.0 {
            self.reload();
        }
        // the log on screen, as soon as it grows
        if let Some(r) = &mut self.reader {
            if r.view == View::Log && !r.task.log.is_empty() && log_stamp(&r.task.log) != r.log_seen {
                r.fill(self.age);
            }
        }
    }

    /// Opens the reader on the selected card.
    fn read(&mut self, view: View) {
        let Some(t) = self.current().cloned() else {
            return self.warn("no card selected".into());
        };
        let mut r = Reader::new(t, view);
        r.fill(self.age);
        self.reader = Some(r);
    }

    /// Back to the overview, on the reader's card while it is on the board.
    fn close(&mut self) {
        if let Some(r) = self.reader.take() {
            if let Some(i) = self.board.iter().position(|t| t.id == r.task.id) {
                self.selected.select(Some(i));
            }
        }
    }

    /// A failure in the status line, in yellow.
    fn warn(&mut self, message: String) {
        (self.status, self.alert) = (message, true);
    }

    fn key(&mut self, code: KeyCode) {
        self.alert = false;
        if let Some((t, _)) = self.confirm.take() {
            match code {
                KeyCode::Char('g') | KeyCode::Enter => self.launch = Some(t.id),
                _ => self.status = "Lazygit not opened".into(),
            }
            return;
        }
        match code {
            KeyCode::Char('q') => self.quit = true,
            KeyCode::Esc => self.close(),
            KeyCode::Char('b') => {
                let url = self.focused().map(|t| self.pr_of(t).unwrap_or_else(|| t.url.clone())).unwrap_or_default();
                self.status = open_url(&url);
            }
            KeyCode::Char('o') => {
                if let Some(id) = self.focused().map(|t| t.id.clone()) {
                    self.status = match Command::new("task").args(["open", &id]).stdin(Stdio::null()).output() {
                        Ok(o) => String::from_utf8_lossy(&o.stdout).lines().find(|l| !l.trim().is_empty())
                            .unwrap_or("task open: no output").trim().to_string(),
                        Err(e) => format!("cannot run task open: {e}"),
                    };
                }
            }
            KeyCode::Char('g') => match self.focused().map(|t| (t.id.clone(), t.title.clone())) {
                None => self.warn("no card selected: Lazygit not opened".into()),
                Some((id, title)) => match lazygit_target(&id) {
                    Ok(t) => self.confirm = Some((t, title)),
                    Err(e) => self.warn(e),
                },
            },
            KeyCode::Char('f') if self.fetching.is_none() => {
                let (tx, rx) = mpsc::channel();
                thread::spawn(move || {
                    let _ = tx.send(fetch());
                });
                self.fetching = Some(rx);
                self.status = "fetching from GitHub (read only)…".into();
            }
            // in the reader, the other keys move in it and never change the task
            code if self.reader.is_some() => {
                let age = self.age;
                if let Some(r) = &mut self.reader {
                    r.key(code, age);
                }
            }
            KeyCode::Down | KeyCode::Char('j') => {
                self.selected.select_next();
                self.details = 0;
            }
            KeyCode::Up | KeyCode::Char('k') => {
                self.selected.select_previous();
                self.details = 0;
            }
            KeyCode::PageDown | KeyCode::Char(' ') => self.details = self.details.saturating_add(self.details_page),
            KeyCode::PageUp => self.details = self.details.saturating_sub(self.details_page),
            KeyCode::Enter => self.read(View::Issue),
            KeyCode::Char('d') => self.read(View::Diff),
            KeyCode::Char('l') => self.read(View::Log),
            _ => {}
        }
    }

    /// The wheel scrolls the reader (the terminal reports it only there), not behind the Lazygit confirmation.
    fn mouse(&mut self, kind: MouseEventKind) {
        let Some(r) = self.reader.as_mut().filter(|_| self.confirm.is_none()) else { return };
        match kind {
            MouseEventKind::ScrollDown => r.scroll(WHEEL),
            MouseEventKind::ScrollUp => r.scroll(-WHEEL),
            MouseEventKind::ScrollRight => r.sideways(SIDEWAYS as isize),
            MouseEventKind::ScrollLeft => r.sideways(-(SIDEWAYS as isize)),
            _ => {}
        }
    }

    fn pr_of(&self, t: &Task) -> Option<String> {
        if !t.pr.is_empty() {
            return Some(t.pr.clone());
        }
        let (last, digest) = self.last_events(&t.id);
        [last, digest].into_iter().flatten().map(|e| text(e, "pr")).find(|p| !p.is_empty())
    }

    fn draw(&mut self, f: &mut Frame) {
        let status = if self.error.is_empty() { self.status.clone() } else { format!("error: {}", self.error) };
        let keys = match &self.reader {
            None => KEYS.to_string(),
            Some(r) => {
                let sideways = if r.view == View::Diff { "←→ sideways  " } else { "" };
                format!("↑↓ jk scroll  {sideways}PgUp/PgDn/Space page  Home/End  ⏎ issue  d diff  l log  g lazygit  \
                         b browser  Esc back  q quit")
            }
        };
        // the keys, then the status; up to 3 lines, so that a long error and its help are not cut off
        let width = (keys.chars().count() + status.chars().count() + 4).max(1);
        let foot_rows = width.div_ceil((f.area().width as usize).saturating_sub(10).max(1)).clamp(1, 3) as u16;
        let [head, body, foot] = Layout::vertical([Constraint::Length(1), Constraint::Min(1), Constraint::Length(foot_rows)])
            .areas(f.area());
        match &mut self.reader {
            Some(r) => r.draw(f, head, body),
            None => self.draw_overview(f, head, body),
        }

        let status = if self.alert { format!("  {status}").yellow() } else { format!("  {status}").dim() };
        let foot_line = Line::from(vec![format!(" {keys} ").reversed(), status]);
        f.render_widget(Paragraph::new(foot_line).wrap(Wrap { trim: false }), foot);

        if let Some((t, title)) = &self.confirm {
            let area = f.area();
            let (w, h) = (area.width.saturating_sub(4).min(90), area.height.saturating_sub(2).min(22));
            let popup = Rect::new(area.x + (area.width - w) / 2, area.y + (area.height - h) / 2, w, h);
            f.render_widget(Clear, popup);
            let block = Block::bordered().title(" Open Lazygit? It can change Git ").border_style(Style::new().yellow())
                .title_bottom(Line::from(" g or ⏎ open Lazygit · any other key cancels ").bold());
            f.render_widget(Paragraph::new(handoff_lines(t, title)).block(block).wrap(Wrap { trim: false }), popup);
        }
    }

    /// The overview, for choosing a task: the board, the selected card's details, and the newest events.
    fn draw_overview(&mut self, f: &mut Frame, head: Rect, body: Rect) {
        // the events give up rows first in a short terminal
        let [body, feed] = Layout::vertical([Constraint::Min(6), Constraint::Length((f.area().height / 4).clamp(3, 9))])
            .areas(body);
        // side by side when wide, the details under the board in a narrow pane
        let [left, right] = if body.width >= 110 {
            Layout::horizontal([Constraint::Percentage(50), Constraint::Percentage(50)]).areas(body)
        } else {
            Layout::vertical([Constraint::Percentage(45), Constraint::Percentage(55)]).areas(body)
        };

        let needs = self.board.iter().filter(|t| ["Backlog", "In review", "Blocked"].contains(&t.status.as_str())).count();
        let running = self.board.iter().filter(|t| t.running).count();
        let mut head_spans = vec![
            " task-rs ".bold().reversed(),
            format!(" needs you {needs}").bold(),
            format!(" · {running} running · {} open · board {} ago", self.board.len(), ago(self.age)).into(),
        ];
        if self.changed {
            head_spans.push(" (changed: f)".yellow());
        }
        f.render_widget(Line::from(head_spans), head);

        self.draw_board(f, left);
        self.draw_details(f, right);
        self.draw_events(f, feed);
    }

    fn draw_board(&mut self, f: &mut Frame, area: Rect) {
        let items: Vec<ListItem> = self.board.iter().map(|t| {
            let mut spans = vec![
                Span::styled(format!("#{:<4}", t.id), Style::new().dim()),
                Span::styled(format!("{:<8} ", tag(t)), Style::new().fg(color(&t.status))),
                Span::raw(t.title.clone()),
            ];
            if !t.waits_for.is_empty() {
                spans.push(Span::styled("  ⏳", Style::new().dim()));
            }
            ListItem::new(Line::from(spans))
        }).collect();
        let list = List::new(items)
            .block(Block::bordered().title(" Board "))
            .highlight_style(Style::new().add_modifier(Modifier::REVERSED))
            .highlight_symbol("▶ ");
        f.render_stateful_widget(list, area, &mut self.selected);
    }

    fn draw_details(&mut self, f: &mut Frame, area: Rect) {
        let Some(t) = self.current() else {
            f.render_widget(Paragraph::new("no open cards").block(Block::bordered().title(" Details ")), area);
            return;
        };
        let field = |k: &str, v: String| Line::from(vec![Span::styled(format!("{k:<9}"), Style::new().dim()), v.into()]);
        let mut lines = vec![
            Line::from(format!("#{} {}", t.id, t.title)).bold(),
            Line::default(),
            Line::from(vec![Span::styled(format!("{:<9}", "status"), Style::new().dim()),
                            Span::styled(shown_status(t), Style::new().fg(color(&t.status)))]),
            field("repo", t.repo.clone()),
            field("agent", if t.agent.is_empty() { "default".into() } else { t.agent.clone() }),
            field("issue", t.url.clone()),
        ];
        if let Some(pr) = self.pr_of(t) {
            lines.push(field("pr", pr));
        }
        if !t.waits_for.is_empty() {
            lines.push(field("waits for", t.waits_for.clone()));
        }
        let (last, digest) = self.last_events(&t.id);
        if let Some(e) = last {
            lines.push(field("last", format!("{} at {}", text(e, "event"), local_time(&text(e, "time"), self.offset))));
        }
        if let Some(e) = digest {
            lines.push(Line::default());
            lines.push(Line::from(format!("digest of {} at {}", text(e, "event"), local_time(&text(e, "time"), self.offset))).underlined());
            let d = &e["digest"];
            for k in ["verdict", "reason", "decision", "question", "answer", "goal_change"] {
                let v = text(d, k);
                if !v.is_empty() {
                    lines.push(field(k, v));
                }
            }
            for item in d["review"].as_array().into_iter().flatten() {
                lines.push(Line::from(format!("• {}", super::shown(item))));
            }
            let report = text(d, "report");
            if !report.is_empty() {
                lines.push(Line::default());
                lines.extend(report.lines().map(|l| Line::from(l.to_string())));
            }
        }
        let block = Block::bordered().title(" Details ");
        let inner = block.inner(area);
        f.render_widget(block, area);
        // PgUp and PgDn scroll it, kept within the wrapped text
        let rows = screen_rows(&lines, inner.width, true);
        self.details_page = (inner.height as usize).max(1);
        self.details = self.details.min(rows.iter().sum::<usize>().saturating_sub(inner.height as usize));
        draw_rows(f, inner, &lines, &rows, true, self.details, 0);
    }

    fn draw_events(&self, f: &mut Frame, area: Rect) {
        let wanted: HashMap<&str, Color> = [("In review", Color::Green), ("Blocked", Color::Red), ("Done", Color::Blue),
                                            ("replan", Color::Magenta), ("slow", Color::Yellow)].into();
        let rows = area.height.saturating_sub(2) as usize;
        let shown: Vec<&Value> = self.events.iter().rev().take(rows).collect();
        let times: Vec<String> = shown.iter().map(|e| local_time(&text(e, "time"), self.offset)).collect();
        let width = times.iter().map(|t| t.len()).max().unwrap_or(5);
        let lines: Vec<Line> = shown.iter().zip(&times).map(|(e, time)| {
            let name = text(e, "event");
            let style = Style::new().fg(*wanted.get(name.as_str()).unwrap_or(&Color::Gray));
            Line::from(vec![
                Span::styled(format!("{time:>width$} "), Style::new().dim()),
                Span::styled(format!("#{:<4}", super::shown(&e["id"])), Style::new().dim()),
                Span::styled(format!("{name:<12} "), style),
                Span::raw(text(e, "title")),
            ])
        }).collect();
        f.render_widget(Paragraph::new(lines).block(Block::bordered().title(" Events ")), area);
    }
}

/// `stty` on the terminal (Unix): its output, or None when it fails.
fn stty(args: &[&str]) -> Option<String> {
    if !cfg!(unix) {
        return None;
    }
    let o = Command::new("stty").args(args).stdin(Stdio::inherit()).stderr(Stdio::null()).output().ok()?;
    o.status.success().then(|| String::from_utf8_lossy(&o.stdout).trim().to_string())
}

/// Lends the terminal to Lazygit in the task's worktree, waits for it, then takes the terminal back and reloads.
/// Checks the worktree again first: the run may have ended, or task watch removed it, since the confirmation.
/// Opening and quitting Lazygit change nothing: no task status, run file, fetch or Git command of task-rs.
fn lazygit(terminal: &mut DefaultTerminal, app: &mut App, id: &str) -> std::io::Result<()> {
    let t = match lazygit_target(id) {
        Ok(t) => t,
        Err(e) => {
            app.warn(e);
            return Ok(());
        }
    };
    let Some(program) = lazygit_path() else {
        app.warn("lazygit is not on PATH: install it (brew install lazygit, see rust/README.md). Nothing opened".into());
        return Ok(());
    };
    let wt = tilde(&t.worktree);
    terminal.show_cursor()?;
    execute!(std::io::stdout(), DisableMouseCapture)?; // the reader's wheel reports: Lazygit asks for its own
    ratatui::try_restore()?; // the normal screen, in cooked mode: Lazygit sets up the terminal its own way
    let mode = stty(&["-g"]); // that mode, put back even if Lazygit dies in raw mode
    println!("task-rs: Lazygit in #{id}, {wt}. Quit Lazygit to return to the board.");
    let result = Command::new(&program).current_dir(&t.worktree).status(); // inherits stdin, stdout and stderr
    // take the terminal back even when Lazygit failed or left it in another state
    match mode.filter(|m| !m.is_empty()) {
        Some(mode) => stty(&[&mode]),
        None => stty(&["sane"]),
    };
    execute!(std::io::stdout(), DisableMouseCapture, DisableBracketedPaste, DisableFocusChange)?;
    if matches!(&result, Ok(s) if !s.success()) {
        // keep what Lazygit printed (a config error, say) on the screen until it is read
        print!("task-rs: Lazygit did not end normally (see above). Press Enter to return to the board.");
        std::io::Write::flush(&mut std::io::stdout())?;
        std::io::stdin().read_line(&mut String::new())?;
    }
    enable_raw_mode()?;
    execute!(std::io::stdout(), EnterAlternateScreen, ClearScreen(ClearType::All))?;
    // a new Terminal draws everything again; terminal.clear() would ask the terminal where its cursor is
    *terminal = Terminal::new(CrosstermBackend::new(std::io::stdout()))?;
    while event::poll(Duration::ZERO)? {
        event::read()?; // keys meant for Lazygit, typed as it ended
    }
    app.reload(); // keeps the selected card by its id, and the reader where it was
    match result {
        Ok(s) if s.success() => app.status = format!("back from Lazygit in #{id}; board reloaded (read only)"),
        Ok(s) => app.warn(match s.code() {
            Some(code) => format!("Lazygit exited with code {code} in #{id} ({wt}); board reloaded"),
            None => format!("Lazygit was stopped by a signal in #{id} ({wt}); board reloaded"),
        }),
        Err(e) => app.warn(format!("cannot start Lazygit ({}) in {wt}: {e}", program.display())),
    }
    Ok(())
}

fn main_loop(terminal: &mut DefaultTerminal) -> std::io::Result<()> {
    let mut app = App::new();
    // the terminal reports the wheel in the reader only: on the board it keeps its own mouse selection
    let mut mouse = false;
    while !app.quit {
        if mouse != app.reader.is_some() {
            mouse = !mouse;
            if mouse {
                execute!(std::io::stdout(), EnableMouseCapture)?;
            } else {
                execute!(std::io::stdout(), DisableMouseCapture)?;
            }
        }
        terminal.draw(|f| app.draw(f))?;
        if event::poll(Duration::from_millis(500))? {
            match event::read()? {
                // Ctrl-D or Ctrl-L is not d or l
                Event::Key(k) if k.kind == KeyEventKind::Press
                    && !k.modifiers.intersects(KeyModifiers::CONTROL | KeyModifiers::ALT) => app.key(k.code),
                Event::Mouse(m) => app.mouse(m.kind),
                _ => {}
            }
        }
        if let Some(id) = app.launch.take() {
            lazygit(terminal, &mut app, &id)?;
            mouse = false; // lazygit() turned the reports off
        }
        app.tick();
    }
    Ok(())
}

pub fn run() {
    board_config(); // a missing config stops here, before the screen is taken over
    if open_in_herdr_pane() {
        return;
    }
    let hook = std::panic::take_hook(); // ratatui's hook restores the screen, then this one turns the wheel reports off
    std::panic::set_hook(Box::new(move |info| {
        let _ = execute!(std::io::stdout(), DisableMouseCapture);
        hook(info);
    }));
    let result = ratatui::run(main_loop);
    let _ = execute!(std::io::stdout(), DisableMouseCapture); // ratatui does not turn the wheel reports off
    if let Err(e) = result {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}

/// Started inside herdr but not on a terminal (by an agent, say): open a herdr pane to the right of this one and run
/// the TUI there, instead of failing with no screen. TASK_HERDR=0 turns this off, as for bin/task.
fn open_in_herdr_pane() -> bool {
    let Ok(pane) = env::var("HERDR_PANE_ID") else { return false };
    if env::var("TASK_HERDR").as_deref() == Ok("0") || std::io::IsTerminal::is_terminal(&std::io::stdout()) {
        return false;
    }
    let herdr = env::var("HERDR_BIN_PATH").unwrap_or_else(|_| "herdr".into());
    let herdr_out = |args: &[&str]| match Command::new(&herdr).args(args).stdin(Stdio::null()).output() {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).into_owned(),
        Ok(o) => fail(&format!("herdr {} failed: {}", args[..2].join(" "), String::from_utf8_lossy(&o.stderr).trim()), "", 1),
        Err(e) => fail(&format!("could not run {herdr}: {e}"), "", 1),
    };
    let cwd = env::current_dir().map(|d| d.to_string_lossy().into_owned()).unwrap_or_default();
    let split = herdr_out(&["pane", "split", "--pane", &pane, "--direction", "right", "--cwd", &cwd, "--focus"]);
    let new = serde_json::from_str::<Value>(&split).ok()
        .and_then(|v| v["result"]["pane"]["pane_id"].as_str().map(String::from))
        .unwrap_or_else(|| fail(&format!("herdr pane split gave no pane id: {}", split.trim()), "", 1));
    // the pane's shell has the herdr server's PATH, not ours: run this same binary by its path
    let exe = env::current_exe().map(|p| p.to_string_lossy().into_owned()).unwrap_or_else(|_| "task-rs".into());
    herdr_out(&["pane", "run", &new, &format!("'{}' tui", exe.replace('\'', "'\\''"))]);
    super::out(&[format!("tui: opened in herdr pane {new}, to the right of {pane}")]);
    true
}
