//! Parsing of the ISO 8601 timestamps Home Assistant uses.
//!
//! Home Assistant renders timestamps as `YYYY-MM-DDTHH:MM:SS.ffffff+00:00`,
//! while callers usually pass the friendlier `...Z` form. To filter a window
//! correctly the two have to be compared as instants, not as strings, so the
//! values are normalised to microseconds since the Unix epoch.
//!
//! Only what the API actually produces is supported; anything else is rejected
//! with a message that tells the caller what was expected.

use std::fmt;

/// Microseconds since 1970-01-01T00:00:00Z.
pub type Micros = i128;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TimestampError {
    /// The value is not an ISO 8601 date-time.
    Malformed,
}

impl fmt::Display for TimestampError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            TimestampError::Malformed => write!(
                f,
                "expected an ISO 8601 timestamp such as 2026-09-22T12:00:00Z or \
                 2026-09-22T12:00:00+02:00 (a bare date like 2026-09-22 also works)"
            ),
        }
    }
}

impl std::error::Error for TimestampError {}

/// Parses an ISO 8601 timestamp into [`Micros`].
pub fn parse(text: &str) -> Result<Micros, TimestampError> {
    let text = text.trim();
    let (date, rest) = match text.split_once(['T', 't']) {
        Some((date, time)) => (date, Some(time)),
        None => (text, None),
    };

    let mut parts = date.split('-');
    let year = next_number(&mut parts, 4)?;
    let month = next_number(&mut parts, 2)?;
    let day = next_number(&mut parts, 2)?;
    if !(1..=12).contains(&month) || !(1..=days_in_month(year, month)).contains(&day) {
        return Err(TimestampError::Malformed);
    }
    let days = to_days(year, month, day);

    if let Some(time) = rest {
        let (time, offset) = split_offset(time)?;
        let mut fields = time.split(':');
        let hour = next_number(&mut fields, 2)?;
        let minute = next_number(&mut fields, 2).unwrap_or(0);
        let (second, micros) = fields
            .next()
            .map(split_fraction)
            .transpose()?
            .unwrap_or((0, 0));
        // 60 is allowed so a leap-second timestamp from Home Assistant is not lost.
        if hour > 23 || minute > 59 || second > 60 || micros > 999_999 {
            return Err(TimestampError::Malformed);
        }

        let (sign, offset_hours, offset_minutes) = offset;
        let delta = (offset_hours * 3600 + offset_minutes * 60) as i128 * sign;
        let seconds_total =
            days * 86_400 + i128::from(hour) * 3_600 + i128::from(minute) * 60 + i128::from(second);
        return Ok((seconds_total - delta) * 1_000_000 + i128::from(micros));
    }

    Ok(days * 86_400 * 1_000_000)
}

fn days_in_month(year: u32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29,
        _ => 28,
    }
}

/// True when `text` parses, used to validate arguments cheaply.
pub fn is_valid(text: &str) -> bool {
    parse(text).is_ok()
}

/// Renders [`Micros`] back to `YYYY-MM-DDTHH:MM:SSZ`, for echoing a window.
pub fn format(value: Micros) -> String {
    let days = value.div_euclid(86_400_000_000);
    let rest = value.rem_euclid(86_400_000_000);
    let (year, month, day) = from_days(days);
    let seconds = rest / 1_000_000;
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        seconds / 3_600,
        (seconds / 60) % 60,
        seconds % 60
    )
}

fn next_number<'a>(
    fields: &mut impl Iterator<Item = &'a str>,
    width: usize,
) -> Result<u32, TimestampError> {
    let raw = fields.next().ok_or(TimestampError::Malformed)?;
    if raw.len() != width || !raw.bytes().all(|b| b.is_ascii_digit()) {
        return Err(TimestampError::Malformed);
    }
    raw.parse::<u32>().map_err(|_| TimestampError::Malformed)
}

/// Splits `12:00:00.500+02:00` into the time part and the normalised offset.
fn split_offset(time: &str) -> Result<(&str, (i128, u32, u32)), TimestampError> {
    let index = time.find(['+', '-']).unwrap_or(time.len());
    let (clock, offset) = time.split_at(index);
    if offset.is_empty() {
        // A trailing `Z` means UTC; no sign to look for.
        return match clock.strip_suffix(['Z', 'z']) {
            Some(clock) => Ok((clock, (1, 0, 0))),
            None => Err(TimestampError::Malformed),
        };
    }
    let sign = if &offset[..1] == "-" { -1 } else { 1 };
    let body = &offset[1..];
    let (hours, minutes) = match body.len() {
        // `+02`, `+0200` and `+02:00` are all legal ISO 8601 spellings.
        2 if body.bytes().all(|b| b.is_ascii_digit()) => {
            (body.parse().map_err(|_| TimestampError::Malformed)?, 0)
        }
        _ if body.len() == 4 && body.bytes().all(|b| b.is_ascii_digit()) => (
            body[..2].parse().map_err(|_| TimestampError::Malformed)?,
            body[2..].parse().map_err(|_| TimestampError::Malformed)?,
        ),
        _ if body.len() == 5
            && body.as_bytes()[2] == b':'
            && body[..2].bytes().all(|b| b.is_ascii_digit())
            && body[3..].bytes().all(|b| b.is_ascii_digit()) =>
        {
            (
                body[..2].parse().map_err(|_| TimestampError::Malformed)?,
                body[3..].parse().map_err(|_| TimestampError::Malformed)?,
            )
        }
        _ => return Err(TimestampError::Malformed),
    };
    if hours > 23 || minutes > 59 {
        return Err(TimestampError::Malformed);
    }
    Ok((clock, (sign, hours, minutes)))
}

/// Splits `06` or `06.25` into whole seconds and microseconds.
fn split_fraction(raw: &str) -> Result<(u32, u32), TimestampError> {
    match raw.split_once('.') {
        Some((whole, fraction)) => {
            let seconds = next_number(&mut std::iter::once(whole), 2)?;
            if fraction.is_empty()
                || fraction.len() > 6
                || !fraction.bytes().all(|b| b.is_ascii_digit())
            {
                return Err(TimestampError::Malformed);
            }
            let padded = format!("{fraction:0<6}");
            Ok((
                seconds,
                padded
                    .parse::<u32>()
                    .map_err(|_| TimestampError::Malformed)?,
            ))
        }
        None => Ok((next_number(&mut std::iter::once(raw), 2)?, 0)),
    }
}

/// Days since the epoch for a proleptic Gregorian date (Howard Hinnant's algorithm).
fn to_days(year: u32, month: u32, day: u32) -> i128 {
    let y = i128::from(year) - i128::from(month <= 2);
    let era = (if y >= 0 { y } else { y - 399 }) / 400;
    let yoe = y - era * 400;
    let mp = i128::from((month + 9) % 12);
    let doy = (153 * mp + 2) / 5 + i128::from(day) - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// Inverse of [`to_days`].
fn from_days(days: i128) -> (i128, u32, u32) {
    let days = days + 719_468;
    let era = if days >= 0 { days } else { days - 146_096 } / 146_097;
    let doe = days - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if month <= 2 { year + 1 } else { year }, month, day)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_the_forms_home_assistant_and_clients_produce() {
        assert_eq!(parse("1970-01-01T00:00:00Z"), Ok(0));
        assert_eq!(parse("1970-01-01T00:00:00.000000+00:00"), Ok(0));
        assert_eq!(parse("2026-09-22T12:00:00Z"), Ok(1_790_078_400_000_000));
        assert_eq!(
            parse("2026-09-22T12:00:00.500Z"),
            Ok(1_790_078_400_500_000),
            "fractional seconds are honoured"
        );
        assert_eq!(
            parse("2026-09-22T14:00:00+02:00"),
            Ok(1_790_078_400_000_000),
            "offsets are normalised to UTC"
        );
        assert_eq!(
            parse("2026-09-22T10:00:00-02:00"),
            Ok(1_790_078_400_000_000)
        );
        assert_eq!(
            parse("2026-09-22T14:00:00+0200"),
            Ok(1_790_078_400_000_000),
            "compact offsets are accepted"
        );
        assert_eq!(
            parse("2026-09-22T14:00+02:00"),
            Ok(1_790_078_400_000_000),
            "seconds may be omitted"
        );
    }

    #[test]
    fn calendar_rules_are_enforced() {
        assert!(is_valid("2024-02-29"), "2024 is a leap year");
        assert!(!is_valid("2026-02-29"), "2026 is not");
        assert!(
            is_valid("2026-09-22T23:59:60Z"),
            "leap seconds are tolerated"
        );
        assert!(!is_valid("2026-09-22T24:00:00Z"));
    }

    #[test]
    fn home_assistant_output_compares_equal_to_the_utc_spelling() {
        let ha = parse("2026-09-22T12:25:55.216357+00:00").expect("HA format");
        let plain = parse("2026-09-22T12:25:55Z").expect("plain format");
        assert!(ha > plain && ha - plain < 1_000_000);
    }

    #[test]
    fn a_bare_date_is_midnight_utc() {
        assert_eq!(
            parse("2026-09-22"),
            Ok(parse("2026-09-22T00:00:00Z").unwrap())
        );
        assert_eq!(parse(" 2026-09-22 "), Ok(parse("2026-09-22").unwrap()));
    }

    #[test]
    fn ordering_matches_chronology_across_offsets() {
        // 23:00 at UTC-5 is 04:00Z the next day, i.e. after 03:00Z.
        let later = parse("2026-01-01T23:00:00-05:00").unwrap();
        let earlier = parse("2026-01-02T03:00:00Z").unwrap();
        assert!(earlier < later);
    }

    #[test]
    fn rejects_nonsense_with_a_helpful_message() {
        for bad in [
            "",
            "yesterday",
            "2026-13-01T00:00:00Z",
            "2026-1-1T00:00:00Z",
            "2026-02-30T00:00:00Z",
            "2026-04-31",
            "2026-09-22T12:61:00Z",
            "2026-09-22T25:00:00Z",
            "2026-09-22T12:00:00PST",
            "2026-09-22T12:00:00+2:00",
            "2026-09-22T12:00:00+99:00",
            "2026-09-22 12:00:00",
            "2026-09-22T12:00:xx",
        ] {
            assert_eq!(
                parse(bad),
                Err(TimestampError::Malformed),
                "accepted {bad:?}"
            );
            assert!(!is_valid(bad));
        }
        assert!(parse("yesterday")
            .unwrap_err()
            .to_string()
            .contains("ISO 8601"));
    }

    #[test]
    fn formats_round_trip() {
        for value in [0, 1_790_078_400_000_000, -86_400_000_000] {
            let rendered = format(value);
            assert_eq!(
                parse(&rendered),
                Ok(value),
                "round trip of {value} via {rendered}"
            );
        }
        assert_eq!(format(0), "1970-01-01T00:00:00Z");
        assert_eq!(format(1_790_078_400_000_000), "2026-09-22T12:00:00Z");
        assert_eq!(format(-86_400_000_000), "1969-12-31T00:00:00Z");
    }

    #[test]
    fn day_arithmetic_covers_leap_years_and_the_epoch() {
        assert_eq!(parse("1970-01-01"), Ok(0));
        assert_eq!(parse("1970-01-02"), Ok(86_400_000_000));
        assert_eq!(
            parse("2024-03-01").unwrap() - parse("2024-02-28").unwrap(),
            2 * 86_400_000_000,
            "2024 is a leap year"
        );
        assert_eq!(
            parse("2023-03-01").unwrap() - parse("2023-02-28").unwrap(),
            86_400_000_000
        );
        assert!(
            parse("1969-12-31").unwrap() < 0,
            "dates before the epoch go negative"
        );
    }
}
