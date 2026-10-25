//! Today's pixel art for the board: a small picture and a line to cheer you on, a different one each day.
//! Each picture is drawn with half blocks (`▀` `▄`), two pixels a row, so that its pixels are square.

use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};

/// A picture, row by row (an even number of rows, all as wide), and its line. `.` is empty, a letter is a color (`color`).
pub struct Art {
    pub rows: [&'static str; 10],
    pub line: &'static str,
}

pub const ARTS: [Art; 7] = [
    Art { line: "You're doing great.", rows: [
        "..........",
        ".RR....RR.",
        "RRRR..RRRR",
        "RWRRRRRRRR",
        "RRRRRRRRRR",
        "RRRRRRRRRR",
        ".RRRRRRRR.",
        "..RRRRRR..",
        "...RRRR...",
        "....RR....",
    ] },
    Art { line: "New day, fresh board.", rows: [
        ".....Y.....",
        ".Y...Y...Y.",
        "..Y.....Y..",
        "....OOO....",
        "...OYYYO...",
        "YY.OYYYO.YY",
        "...OYYYO...",
        "....OOO....",
        "..Y.....Y..",
        ".Y...Y...Y.",
    ] },
    Art { line: "One card at a time.", rows: [
        "...g..g...",
        "....g..g..",
        "...g..g...",
        "..........",
        ".WWWWWWW..",
        ".WCCCCCWWW",
        ".WCCCCCW.W",
        ".WCCCCCWWW",
        ".WWWWWWW..",
        "..WWWWW...",
    ] },
    Art { line: "Stretch, then ship.", rows: [
        ".K......K.",
        ".KK....KK.",
        ".KPK..KPK.",
        ".KKKKKKKK.",
        "KKGKKKKGKK",
        "KKGKKKKGKK",
        "KKKKPPKKKK",
        ".KKKKKKKK.",
        "..KKKKKK..",
        "..........",
    ] },
    Art { line: "Ready → Done. Let's go!", rows: [
        "....RR....",
        "...RWWR...",
        "...WWWW...",
        "...WBBW...",
        "...WBBW...",
        "...WWWW...",
        "..RWWWWR..",
        ".RRWWWWRR.",
        "...OYYO...",
        "....OO....",
    ] },
    Art { line: "Small steps grow big.", rows: [
        "..........",
        "..GG..GG..",
        ".GGGG.GGG.",
        ".GGGGGGG..",
        "....GG....",
        "....G.....",
        "....G.....",
        ".TTTTTTTT.",
        "..TTTTTT..",
        "..TTTTTT..",
    ] },
    Art { line: "Every merged PR counts.", rows: [
        "....YY....",
        "....YY....",
        "...YYYY...",
        "YYYYYYYYYY",
        ".YYYYYYYY.",
        "..YYYYYY..",
        "..YYYYYY..",
        ".YYY..YYY.",
        ".YY....YY.",
        "..........",
    ] },
];

/// The color of a pixel, from the 256 colors that every terminal draws. None: empty, the terminal's own background.
fn color(c: char) -> Option<Color> {
    let i = match c {
        'R' => 196, // red
        'W' => 231, // white
        'Y' => 220, // yellow
        'O' => 208, // orange
        'C' => 94,  // coffee
        'g' => 250, // steam
        'K' => 214, // cat
        'P' => 218, // pink
        'G' => 40,  // green
        'B' => 39,  // window
        'T' => 130, // pot
        _ => return None,
    };
    Some(Color::Indexed(i))
}

/// Today's picture: the local day picks it, so it changes at midnight.
pub fn today(now: f64, offset: i64) -> &'static Art {
    &ARTS[(now as i64 + offset).div_euclid(86400).rem_euclid(ARTS.len() as i64) as usize]
}

/// The picture's terminal rows: a pixel above another in one cell, `▀` with the upper's color over the lower's.
pub fn lines(art: &Art) -> Vec<Line<'static>> {
    art.rows.chunks(2).map(|pair| {
        Line::from(pair[0].chars().zip(pair[1].chars()).map(|(up, down)| match (color(up), color(down)) {
            (None, None) => Span::raw(" "),
            (Some(u), None) => Span::styled("▀", Style::new().fg(u)),
            (None, Some(d)) => Span::styled("▄", Style::new().fg(d)),
            (Some(u), Some(d)) => Span::styled("▀", Style::new().fg(u).bg(d)),
        }).collect::<Vec<_>>())
    }).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_picture_has_known_colors_and_rows_as_wide() {
        for art in &ARTS {
            let width = art.rows[0].chars().count();
            for row in art.rows {
                assert_eq!(row.chars().count(), width, "{}", art.line);
                assert!(row.chars().all(|c| c == '.' || color(c).is_some()), "{}: {row}", art.line);
            }
        }
    }

    #[test]
    fn the_picture_changes_with_the_local_day() {
        let day = 86400.0;
        let (a, b) = (today(10.0 * day, 0) as *const Art, today(11.0 * day, 0) as *const Art);
        assert_ne!(a, b);
        // 23:00 UTC is already the next day nine hours east
        assert_eq!(today(11.0 * day - 3600.0, 9 * 3600) as *const Art, b);
    }
}
