const zone = "America/Los_Angeles";
const dateKey = new Intl.DateTimeFormat("en-CA", {
  timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
});
const headingDate = new Intl.DateTimeFormat("en-US", {
  timeZone: "UTC", weekday: "long", month: "long", day: "numeric",
});
const clock = new Intl.DateTimeFormat("en-US", {
  timeZone: zone, hour: "numeric", minute: "2-digit", timeZoneName: "short",
});
const updatedDate = new Intl.DateTimeFormat("en-US", {
  timeZone: zone, dateStyle: "medium", timeStyle: "short",
});
const teamFilter = document.querySelector("#team");
const range = document.querySelector("#range");
const summary = document.querySelector("#summary");
const schedule = document.querySelector("#schedule");
const updated = document.querySelector("#updated");
const sources = document.querySelector("#sources");

function element(tag, label, className) {
  const node = document.createElement(tag);
  if (label) node.textContent = label;
  if (className) node.className = className;
  return node;
}

async function json(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error("Schedule download failed");
  return response.json();
}

function render(teams, data) {
  const today = dateKey.format(new Date());
  const last = new Date(today + "T12:00:00Z");
  last.setUTCDate(last.getUTCDate() + Number(range.value) - 1);
  const through = last.toISOString().slice(0, 10);
  const selected = data.teams.filter(team => !teamFilter.value || team.id === teamFilter.value);
  const games = selected.flatMap(team => team.games
    .filter(game => game.day >= today && game.day <= through)
    .map(game => ({ ...game, team: teams.get(team.id) })))
    .sort((a, b) => a.day.localeCompare(b.day) ||
      (a.start ? Date.parse(a.start) : Infinity) - (b.start ? Date.parse(b.start) : Infinity) ||
      a.team.name.localeCompare(b.team.name));

  schedule.replaceChildren();
  const unavailable = selected.filter(team => team.unavailable);
  const notices = [games.length ? games.length + (games.length === 1 ? " game" : " games") :
    "No games listed for this date range."];
  if (unavailable.length) notices.push("Schedule unavailable for " +
    unavailable.map(team => teams.get(team.id).name).join(", ") + ".");
  if (through > data.through) notices.push("Latest refresh covers through " + data.through + ".");
  summary.textContent = notices.join(" ");

  let day;
  let section;
  for (const game of games) {
    if (game.day !== day) {
      day = game.day;
      section = element("section", "", "day");
      section.append(element("h2", headingDate.format(new Date(day + "T12:00:00Z"))));
      schedule.append(section);
    }
    const row = element("article", "", "game");
    const time = element("div", game.status || (game.start ? clock.format(new Date(game.start)) : "Time TBD"), "clock");
    const matchup = element("div");
    matchup.append(element("strong", game.matchup), element("div", game.team.name + " · " + game.team.group, "meta"));
    const location = element("div", [game.venue, game.city].filter(Boolean).join(" · ") || "Location TBD", "meta");
    row.append(time, matchup, location);
    section.append(row);
  }
}

try {
  const [config, data] = await Promise.all([json("./teams.json"), json("./schedule.json")]);
  const teams = new Map(config.map(team => [team.id, team]));
  for (const team of config) {
    const option = element("option", team.name);
    option.value = team.id;
    teamFilter.append(option);
    const provider = data.teams.find(record => record.id === team.id);
    if (!provider) continue;
    const link = element("a", team.name);
    link.href = provider.source;
    const item = element("li");
    item.append(link);
    sources.append(item);
  }
  updated.textContent = (data.demo ? "Sample data · " : "") +
    "Pacific time · Updated " + updatedDate.format(new Date(data.generatedAt)) + " PT";
  const update = () => render(teams, data);
  teamFilter.addEventListener("change", update);
  range.addEventListener("change", update);
  update();
} catch (error) {
  updated.textContent = "Pacific time";
  summary.textContent = "Schedule data could not be loaded. Try again after the next refresh.";
  console.error(error);
}
