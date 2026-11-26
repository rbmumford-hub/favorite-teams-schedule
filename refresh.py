"""Fetch public schedules and write the GitHub Pages snapshot."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import json
import re
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent / "site"
PACIFIC = ZoneInfo("America/Los_Angeles")
EASTERN = ZoneInfo("America/New_York")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/"
HUSKIES = "https://gohuskies.com"
TORRENT = "https://www.thepwhl.com/en/teams/seattle-torrent/schedule"


def fetch(url):
    request = Request(url, headers={"User-Agent": "FavoriteTeamsSchedule/1.0"})
    with urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8-sig")


def game(day, time, matchup, venue="", city="", status=""):
    return dict(day=day.isoformat(), start=time.isoformat() if time else None,
                matchup=matchup, venue=venue, city=city, status=status)


def espn(team, today):
    events = {}
    endpoint = f"{ESPN}{team['provider']}/teams/{team['code']}/schedule"
    # The default feed can move to the next season while the current year still
    # has games. Include date-window years to cover the New Year transition.
    for query in ("", f"?season={(today + timedelta(days=35)).year}") if (today + timedelta(days=35)).year != today.year else ("",):
        data = json.loads(fetch(endpoint + query))
        if not isinstance(data.get("events"), list):
            raise ValueError("Unexpected ESPN schedule response")
        for event in data["events"]:
            events[event["id"]] = event
    for event in events.values():
        for contest in event.get("competitions", []):
            stamp = contest.get("date", event.get("date"))
            if not stamp:
                continue
            start = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            status = contest.get("status", {}).get("type", {})
            if status.get("completed") or status.get("state") in ("in", "post"):
                continue
            venue = contest.get("venue") or {}
            address = venue.get("address") or {}
            region = address.get("state") or address.get("country")
            city = ", ".join(dict.fromkeys(filter(None, (address.get("city"), region))))
            tbd = contest.get("timeValid", event.get("timeValid", True)) is False
            day = start.date() if tbd else start.astimezone(PACIFIC).date()
            yield game(day, None if tbd else start, event.get("name", "Opponent TBD"),
                       venue.get("fullName", ""), city,
                       status.get("description", "") if status.get("name") in
                       ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED") else "")


def ics_events(text):
    if "BEGIN:VCALENDAR" not in text:
        raise ValueError("Expected an iCalendar response")
    unfolded = re.sub(r"\r?\n[ \t]", "", text)
    for block in re.findall(r"BEGIN:VEVENT\r?\n(.*?)END:VEVENT", unfolded, re.S):
        record = {}
        for line in block.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                name, _, parameters = key.partition(";")
                record[name] = (parameters, re.sub(
                    r"\\([nN,;\\])", lambda m: " " if m[1].lower() == "n" else m[1], value))
        yield record


def huskies(team):
    slug = team["code"]
    page = fetch(f"{HUSKIES}/sports/{slug}/schedule")
    pattern = r"""(?:https?:|webcal:)?(?://gohuskies\.com)?/calendar\.ashx(?:/calendar\.ics)?\?[^"'<>\\\s]+"""
    candidates = [unescape(link) for link in re.findall(pattern, page, re.I)]
    link = next((item for item in candidates if re.search(r"sport_id=\d+", item)), None)
    if not link:
        raise ValueError("Team calendar link was not found on the official schedule")
    link = re.sub(r"^webcal:", "https:", link)
    if link.startswith("/"):
        link = "https:" + link if link.startswith("//") else HUSKIES + link
    for record in ics_events(fetch(link)):
        def value(key):
            return record.get(key, ("", ""))[1]

        parameters, stamp = record.get("DTSTART", ("", ""))
        if not stamp:
            continue
        day = datetime.strptime(stamp[:8], "%Y%m%d").date()
        start = None
        summary = value("SUMMARY")
        if "T" in stamp and not re.search(r"\b(TBA|TBD)\b", summary, re.I):
            tz = re.search(r"TZID=(?:\")?([^;\"]+)", parameters)
            zone = timezone.utc if stamp.endswith("Z") else ZoneInfo(tz[1]) if tz else PACIFIC
            start = datetime.strptime(stamp.rstrip("Z"), "%Y%m%dT%H%M%S").replace(tzinfo=zone)
            day = start.astimezone(PACIFIC).date()
        matchup = re.sub(r"^Washington(?: Huskies)? [\w ’'&-]+?\s+(?=vs\b|at\b)", "", summary)
        if not matchup:
            matchup = "Opponent TBD"
        status = "Canceled" if value("STATUS") == "CANCELLED" else ""
        if re.search(r"\bpostponed\b", summary, re.I):
            status = "Postponed"
        yield game(day, start, matchup, value("LOCATION"), status=status)


class ScheduleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = False
        self.words = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = False

    def handle_data(self, text):
        if not self.hidden and text.strip():
            self.words.append(text.strip())


def torrent(today):
    parser = ScheduleText()
    parser.feed(fetch(TORRENT))
    words = parser.words
    months = r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
    date_pattern = re.compile(rf"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+({months})\s+(\d{{1,2}})\b", re.I)
    time_pattern = re.compile(r"\b(\d{1,2}:\d{2})\s*([ap])\.?\s*m\.?\s*ET\b", re.I)
    matches = 0
    for index, word in enumerate(words):
        match = date_pattern.search(word)
        if not match or index < 2:
            continue
        away, home = words[index - 2:index]
        if "seattle torrent" not in (away.lower(), home.lower()):
            continue
        matches += 1
        upcoming = words[index:index + 9]
        time = time_pattern.search(" ".join(upcoming))
        venue_line = next((line for line in upcoming if " | " in line), "")
        venue, _, city = venue_line.partition(" | ")
        month = datetime.strptime(match[1].title(), "%b").month
        day = min((date(y, month, int(match[2])) for y in range(today.year - 1, today.year + 2) if int(match[2]) <= monthrange(y, month)[1]),
                  key=lambda candidate: abs(candidate - today))
        start = None
        if time:
            clock = datetime.strptime(time[1] + " " + time[2].upper() + "M", "%I:%M %p").time()
            start = datetime.combine(day, clock, EASTERN)
            day = start.astimezone(PACIFIC).date()
        yield game(day, start, f"{away.title()} at {home.title()}", venue, city)
    if not matches:
        raise ValueError("Official Torrent schedule format could not be recognized")


def source(team):
    if team["provider"] == "uw":
        return f"{HUSKIES}/sports/{team['code']}/schedule"
    if team["provider"] == "torrent":
        return TORRENT
    sport, league = team["provider"].split("/")
    return f"https://www.espn.com/{sport}/team/schedule/_/id/{team['code']}"


def snapshot(teams, today, demo):
    end = today + timedelta(days=35)

    def load(team):
        provider = team["provider"]
        result = {"id": team["id"], "source": source(team), "games": []}
        try:
            if demo:
                sample = game(today, None, f"{team['name']} vs. Example opponent",
                              "Example arena", "Seattle, WA")
                games = [sample]
            elif provider == "uw":
                games = huskies(team)
            elif provider == "torrent":
                games = torrent(today)
            else:
                games = espn(team, today)
            unique = {}
            for item in games:
                if today.isoformat() <= item["day"] <= end.isoformat():
                    unique[item["day"], item["start"], item["matchup"]] = item
            result["games"] = list(unique.values())
        except Exception as exc:
            print(f"::warning::{team['name']} schedule unavailable: {exc}", flush=True)
            result["unavailable"] = True
        return result

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(load, teams))
    if all(item.get("unavailable") for item in results):
        raise SystemExit("All schedule sources failed. The previous deployment was preserved.")
    return dict(generatedAt=datetime.now(timezone.utc).isoformat(), through=end.isoformat(),
                demo=demo, teams=results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "schedule.json")
    args = parser.parse_args()
    teams = json.loads((ROOT / "teams.json").read_text(encoding="utf-8"))
    result = snapshot(teams, datetime.now(PACIFIC).date(), args.demo)
    args.output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
