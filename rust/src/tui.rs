//! `task-rs tui`: a live, read-only view of the local board, the runs on this machine, and the events.
//! It reads only local files and redraws when they change. GitHub is read only when the user presses `s`.

use super::{ago, board_config, epoch, load_local, now, shown_status, state, sync, tasks, text, Task};
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEventKind};
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style, Stylize};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, List, ListItem, ListState, Paragraph, Wrap};
use ratatui::{DefaultTerminal, Frame};
use serde_json::Value;
use std::collections::HashMap;
use std::io::{Read, Seek, SeekFrom};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::time::{Duration, SystemTime};
use std::{fs, thread};

/// Columns in the order a person acts on them: what needs you first.
const ORDER: [&str; 7] = ["In review", "Blocked", "In progress", "Ready", "wait for merge", "Backlog", "Done"];
const KEYS: &str = "↑↓ move  ⏎ PR  i Issue  l log  o open  s sync  q quit";

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

/// The last lines of a run's log, without the terminal's color codes.
fn log_tail(path: &str, lines: usize) -> Vec<String> {
    let Ok(mut f) = fs::File::open(path) else { return vec![format!("no log at {path}")] };
    let len = f.metadata().map(|m| m.len()).unwrap_or(0);
    let _ = f.seek(SeekFrom::Start(len.saturating_sub(64 * 1024)));
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
    let all: Vec<&str> = clean.lines().collect();
    all[all.len().saturating_sub(lines)..].iter().map(|l| l.to_string()).collect()
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

struct App {
    board: Vec<Task>,
    age: f64,
    changed: bool,
    error: String,
    events: Vec<Value>,
    selected: ListState,
    show_log: bool,
    status: String,
    offset: i64,
    seen: (Option<SystemTime>, Option<SystemTime>, Option<SystemTime>),
    loaded_at: f64,
    syncing: Option<Receiver<Result<usize, String>>>,
    quit: bool,
}

impl App {
    fn new() -> Self {
        let mut app = App {
            board: vec![], age: 0.0, changed: false, error: String::new(), events: vec![],
            selected: ListState::default(), show_log: false, status: "read only: GitHub is read only when you press s".into(),
            offset: utc_offset(), seen: (None, None, None), loaded_at: 0.0, syncing: None, quit: false,
        };
        app.reload();
        app
    }

    fn files() -> (Option<SystemTime>, Option<SystemTime>, Option<SystemTime>) {
        (mtime(&state("board-cache.json")), mtime(&state("events.jsonl")), mtime(&state("runs")))
    }

    /// Reads the board, the runs and the events again, keeping the selected card.
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
    }

    fn current(&self) -> Option<&Task> {
        self.selected.selected().and_then(|i| self.board.get(i))
    }

    /// The newest event of a task, and its newest event that carries a digest.
    fn last_events(&self, id: &str) -> (Option<&Value>, Option<&Value>) {
        let mine = self.events.iter().rev().filter(|e| super::shown(&e["id"]) == id);
        let last = mine.clone().next();
        (last, mine.into_iter().find(|e| e["digest"].is_object()))
    }

    fn tick(&mut self) {
        if let Some(rx) = &self.syncing {
            if let Ok(result) = rx.try_recv() {
                self.status = match result {
                    Ok(n) => format!("synced {n} open card(s) from GitHub"),
                    Err(e) => format!("sync failed: {e} (the local board is unchanged)"),
                };
                self.syncing = None;
                self.reload();
                return;
            }
        }
        // files changed, or every 15s for the elapsed times and runs that ended
        if Self::files() != self.seen || now() - self.loaded_at >= 15.0 {
            self.reload();
        }
    }

    fn key(&mut self, code: KeyCode) {
        match code {
            KeyCode::Char('q') | KeyCode::Esc => self.quit = true,
            KeyCode::Down | KeyCode::Char('j') => self.selected.select_next(),
            KeyCode::Up | KeyCode::Char('k') => self.selected.select_previous(),
            KeyCode::Home | KeyCode::Char('g') => self.selected.select_first(),
            KeyCode::End | KeyCode::Char('G') => self.selected.select_last(),
            KeyCode::Char('l') => self.show_log = !self.show_log,
            KeyCode::Char('r') => {
                self.reload();
                self.status = "reloaded the local files".into();
            }
            KeyCode::Enter | KeyCode::Char('p') => {
                let url = self.current().map(|t| self.pr_of(t).unwrap_or_else(|| t.url.clone())).unwrap_or_default();
                self.status = open_url(&url);
            }
            KeyCode::Char('i') => {
                let url = self.current().map(|t| t.url.clone()).unwrap_or_default();
                self.status = open_url(&url);
            }
            KeyCode::Char('o') => {
                if let Some(id) = self.current().map(|t| t.id.clone()) {
                    self.status = match Command::new("task").args(["open", &id]).stdin(Stdio::null()).output() {
                        Ok(o) => String::from_utf8_lossy(&o.stdout).lines().find(|l| !l.trim().is_empty())
                            .unwrap_or("task open: no output").trim().to_string(),
                        Err(e) => format!("cannot run task open: {e}"),
                    };
                }
            }
            KeyCode::Char('s') if self.syncing.is_none() => {
                let (tx, rx) = mpsc::channel();
                thread::spawn(move || {
                    let _ = tx.send(sync());
                });
                self.syncing = Some(rx);
                self.status = "syncing from GitHub…".into();
            }
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
        let [head, body, feed, foot] = Layout::vertical([
            Constraint::Length(1), Constraint::Min(6), Constraint::Length(9), Constraint::Length(1),
        ]).areas(f.area());
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
            head_spans.push(" (changed: s)".yellow());
        }
        f.render_widget(Line::from(head_spans), head);

        self.draw_board(f, left);
        if self.show_log { self.draw_log(f, right) } else { self.draw_details(f, right) }
        self.draw_events(f, feed);

        let status = if self.error.is_empty() { self.status.clone() } else { format!("error: {}", self.error) };
        f.render_widget(Line::from(vec![format!(" {KEYS} ").reversed(), format!("  {status}").dim()]), foot);
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

    fn draw_details(&self, f: &mut Frame, area: Rect) {
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
        let p = Paragraph::new(Text::from(lines)).wrap(Wrap { trim: false })
            .block(Block::bordered().title(" Details (l: log) "));
        f.render_widget(p, area);
    }

    fn draw_log(&self, f: &mut Frame, area: Rect) {
        let (title, lines) = match self.current() {
            Some(t) if !t.log.is_empty() => (format!(" Log #{} (l: details) ", t.id), log_tail(&t.log, area.height as usize)),
            Some(t) => (format!(" Log #{} ", t.id), vec!["no run of this task on this machine".into()]),
            None => (" Log ".into(), vec![]),
        };
        let p = Paragraph::new(lines.join("\n")).block(Block::bordered().title(title));
        f.render_widget(p, area);
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

fn main_loop(terminal: &mut DefaultTerminal) -> std::io::Result<()> {
    let mut app = App::new();
    while !app.quit {
        terminal.draw(|f| app.draw(f))?;
        if event::poll(Duration::from_millis(500))? {
            if let Event::Key(k) = event::read()? {
                if k.kind == KeyEventKind::Press {
                    app.key(k.code);
                }
            }
        }
        app.tick();
    }
    Ok(())
}

pub fn run() {
    board_config(); // a missing config stops here, before the screen is taken over
    if let Err(e) = ratatui::run(main_loop) {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}
