"""std.time: calendar arithmetic, formats, Duration, time zones with daylight saving, leap seconds and GPS time."""
from tests.helpers import run_gg_source

PROGRAM = r'''import std.time

fn main():
    d = time.parse_iso("2024-01-31T12:30:45.123Z").value_or_panic()
    print(d.add_months(1).to_iso(), d.add_years(1).to_iso(), d.day_of_year(), d.weekday_name())
    print(d.format("DD/MM/YYYY HH:mm:ss.SSS ddd MMM"))
    print(time.parse_format("29/02/2024 08:05", "DD/MM/YYYY HH:mm").value_or_panic().to_iso())
    print(time.parse_format("31/02/2024", "DD/MM/YYYY").is_err())
    hol = List[i64]()
    hol.push(time.days_from_civil(2024, 2, 5))
    fri = time.parse_iso("2024-02-02").value_or_panic()
    print(fri.add_business_days(2, hol).to_iso(), fri.add_business_days(-1, hol).to_iso())
    print(time.duration_millis(1500).describe(), time.duration_secs(3723).describe(), time.duration_micros(42).describe())
    ny = time.zone_by_name("America/New_York").value_or_panic()
    t1 = time.parse_iso("2026-03-08T06:59:59Z").value_or_panic().to_unix_millis()
    t2 = time.parse_iso("2026-03-08T07:00:00Z").value_or_panic().to_unix_millis()
    print(ny.to_local(t1).to_iso(), ny.to_local(t2).to_iso(), ny.to_local(t2).is_dst)
    t3 = time.parse_iso("2026-11-01T05:59:59Z").value_or_panic().to_unix_millis()
    print(ny.to_local(t3).to_iso(), ny.to_local(t3 + 1000).to_iso())
    lon = time.zone_by_name("Europe/London").value_or_panic()
    t4 = time.parse_iso("2026-03-29T00:59:59Z").value_or_panic().to_unix_millis()
    print(lon.to_local(t4).to_iso(), lon.to_local(t4 + 1000).to_iso())
    t5 = time.parse_iso("2026-10-25T00:59:59Z").value_or_panic().to_unix_millis()
    print(lon.to_local(t5).to_iso(), lon.to_local(t5 + 1000).to_iso())
    syd = time.zone_by_name("Australia/Sydney").value_or_panic()
    print(syd.to_local(time.parse_iso("2026-01-15T00:00:00Z").value_or_panic().to_unix_millis()).to_iso())
    print(syd.to_local(time.parse_iso("2026-07-15T00:00:00Z").value_or_panic().to_unix_millis()).to_iso())
    print(ny.from_local(time.parse_iso("2026-07-01T09:30:00").value_or_panic()) == time.parse_iso("2026-07-01T13:30:00Z").value_or_panic().to_unix_millis())
    ist = time.zone_by_name("Europe/Istanbul").value_or_panic()
    print(ist.to_local(t1).to_iso())
    # leap seconds / GPS
    j = time.parse_iso("2024-01-01T00:00:00Z").value_or_panic().to_unix_millis()
    print(time.tai_minus_utc(j), time.unix_to_gps_millis(j), time.gps_to_unix_millis(time.unix_to_gps_millis(j)) == j)
    wk = time.gps_week_and_seconds(j)
    print(wk.f0, wk.f1)
    print(time.zone_by_name("Mars/Base").is_none())
'''


def test_time_calendar_zones_and_gps(tmp_path):
    r = run_gg_source(tmp_path, PROGRAM)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "2024-02-29T12:30:45.123Z 2025-01-31T12:30:45.123Z 31 Wednesday",
        "31/01/2024 12:30:45.123 Wed Jan",
        "2024-02-29T08:05:00Z",
        "true",
        "2024-02-07T00:00:00Z 2024-02-01T00:00:00Z",
        "1.500s 1h02m03s 42us",
        "2026-03-08T01:59:59-05:00 2026-03-08T03:00:00-04:00 true",
        "2026-11-01T01:59:59-04:00 2026-11-01T01:00:00-05:00",
        "2026-03-29T00:59:59+00:00 2026-03-29T02:00:00+01:00",
        "2026-10-25T01:59:59+01:00 2026-10-25T01:00:00+00:00",
        "2026-01-15T11:00:00+11:00",
        "2026-07-15T10:00:00+10:00",
        "true",
        "2026-03-08T09:59:59+03:00",
        "37 1388102418000 true",
        "2295 86418",
        "true",
    ]
