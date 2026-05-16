"""
ScoreStream — ESPN Soccer Producer
Polls the ESPN public API every N seconds and publishes game events to Kafka.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
import psycopg2

import requests
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

# ── Config ──────────────────────────────────────────────────────────
KAFKA_SERVERS      = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
POLL_INTERVAL      = int(os.getenv("POLL_INTERVAL_SECONDS", 15))
TOPIC_SCORES       = "epl.live.scores"
TOPIC_STANDINGS    = "epl.standings"

ESPN_SCOREBOARD    = "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard"
ESPN_STANDINGS     = "https://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings"

HEADERS = {"User-Agent": "ScoreStream/1.0"}

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:password@postgres:5432/scorestream")

def get_db():
    return psycopg2.connect(DATABASE_URL)


# ── Kafka setup ─────────────────────────────────────────────────────
def create_producer(retries: int = 10, delay: int = 5) -> KafkaProducer:
    """Retry connecting to Kafka until it's ready."""
    for attempt in range(1, retries + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks="all",               # wait for all replicas to confirm
                retries=3,
            )
            print(f"[producer] Connected to Kafka at {KAFKA_SERVERS}")
            return producer
        except NoBrokersAvailable:
            print(f"[producer] Kafka not ready — attempt {attempt}/{retries}, retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError("Could not connect to Kafka after multiple attempts")


# ── ESPN helpers ─────────────────────────────────────────────────────
poll_count = 0

def fetch_scoreboard() -> list[dict]:
    """Return list of raw game objects from ESPN scoreboard."""
    global poll_count
    poll_count += 1

    dates = [0,1]

    if poll_count % 10 == 0:
        dates.append(-1)

    events = []

    for day_offset in [-1, 0, 1]:  # fetch yesterday's and tomorrow's games to catch late updates
        date_str = (datetime.now() + timedelta(days=day_offset)).strftime("%Y%m%d")
        url = ESPN_SCOREBOARD + f"?dates={date_str}"

        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            day_events = resp.json().get("events", [])
            events.extend(day_events)
        except Exception as e:
            print(f"[producer] Scoreboard fetch error for {date_str}: {e}")
    
    seen = set()
    unique_events = []
    for event in events:
        if event["id"] not in seen:
            unique_events.append(event)
            seen.add(event["id"])

    print(f"[producer] Total unique games fetched across 3 days: {len(unique_events)}")
    return unique_events

def fetch_standings() -> list[dict]:
    """Return raw standings entries from ESPN."""
    try:
        resp = requests.get(ESPN_STANDINGS, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        entries = []

        for group in resp.json().get("children", []):
            for entry in group.get("standings", {}).get("entries", []):
                entries.append(entry)

        return entries
    except Exception as e:
        print(f"[producer] Standings fetch error: {e}")
        return []


def parse_game(game: dict) -> dict | None:
    """Extract a clean game event from a raw ESPN event object."""
    try:
        competition = game["competitions"][0]
        competitors  = competition["competitors"]
        home = next(t for t in competitors if t["homeAway"] == "home")
        away = next(t for t in competitors if t["homeAway"] == "away")
        status =  competition["status"]
        
        goals = []
        for detail in competition.get("details", []):
            if not detail.get("scoringPlay", False):
                continue

            athletes = detail.get("athletesInvolved", [{}])[0]
            goals.append({
                "player_id": athletes.get("id"),
                "player_name": athletes.get("fullName"),
                "team_id": detail["team"]["id"],
                "minute": detail["clock"]["displayValue"],
                "seconds": int(detail["clock"]["value"]),
                "goal_type": detail["type"]["text"],
                "own_goal": detail.get("ownGoal", False),
                "penalty": detail.get("penaltyKick", False),
            })

        cards = []
        for detail in competition.get("details", []):
            if detail.get("scoreValue") != 0:
                continue

            athletes = detail.get("athletesInvolved", [{}])[0]
            cards.append({
                "player_id": athletes.get("id"),
                "player_name": athletes.get("fullName"),
                "team_id": detail["team"]["id"],
                "minute": detail["clock"]["displayValue"],
                "card_type": detail["type"]["text"],
                "yellow_card": detail.get("yellowCard", False),
                "red_card": detail.get("redCard", False),
            })

        return {
            "game_id":    game["id"],
            "home_team_name": home["team"]["displayName"],
            "away_team_name": away["team"]["displayName"],
            "home_team":  home["team"]["abbreviation"],
            "away_team":  away["team"]["abbreviation"],
            "home_id":   home["team"]["id"],
            "away_id":   away["team"]["id"],
            "status":    status["type"]["name"],
            "status_detail": status["type"].get("detail", ""),
            "home_score": int(home.get("score", 0) or 0),
            "away_score": int(away.get("score", 0) or 0),
            "period":    status.get("period", 0),
            "clock":     status.get("displayClock", ""),
            "goals":     goals,
            "cards":     cards,
            "start_time": game.get("date"),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
    except (KeyError, StopIteration) as e:
        print(f"[producer] Could not parse game {game.get('id')}: {e}")
        return None


def parse_standing(entry: dict) -> dict | None:
    """Extract a clean standing record from a raw ESPN standings entry."""
    try:
        stats = {s["name"]: s["value"] for s in entry.get("stats", []) if "value" in s}
        team  = entry["team"]
        return {
            "team_id":   team["id"],
            "team_name": team["displayName"],
            "wins":      int(stats.get("wins", 0)),
            "draws":    int(stats.get("ties", 0)),
            "losses":    int(stats.get("losses", 0)),
            "points":    int(stats.get("points", 0)),
            "goals_for": int(stats.get("pointsFor", 0)),
            "goals_against": int(stats.get("pointsAgainst", 0)),
            "goal_diff": int(stats.get("pointDifferential", 0)),
            "matches_played": int(stats.get("gamesPlayed", 0)),
            "rank": int(stats.get("rank", 0)),
            "deductions": int(stats.get("deductions", 0)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except (KeyError, TypeError) as e:
        print(f"[producer] Could not parse standing: {e}")
        return None


# ── Main loop ────────────────────────────────────────────────────────
def run():
    producer = create_producer()
    poll_count = 0

    conn = get_db()
    cursor = conn.cursor()

    print(f"[producer] Starting — polling every {POLL_INTERVAL}s")
    print(f"[producer] Topics: {TOPIC_SCORES}, {TOPIC_STANDINGS}\n")

    print("[producer] Publishing initial standings on startup...")
    standings = fetch_standings()
    all_standings = []
    
    for entry in standings:
        record = parse_standing(entry)
        if record:
            all_standings.append(record)
    if all_standings:
        producer.send(
            topic=TOPIC_STANDINGS,
            key="full_table",
            value=all_standings,
        )
        producer.flush()
        print(f"[producer] Initial standings published — {len(all_standings)} teams")

    while True:
        poll_count += 1
        print(f"[producer] ── Poll #{poll_count} @ {datetime.now().strftime('%H:%M:%S')} ──")

        # ── Scores ──
        games = fetch_scoreboard()
        published_games = 0
        for game in games:
            event = parse_game(game)
            if event:
                producer.send(
                    topic=TOPIC_SCORES,
                    key=event["game_id"],
                    value=event,
                )
                published_games += 1
                print(f"  [score] {event['away_team']} {event['away_score']} "
                      f"@ {event['home_team']} {event['home_score']} "
                      f"— {event['status_detail']}")

        if published_games == 0:
            print("  [score] No games found (off-season or no games today)")

        # ── Standings (every 3 polls to reduce API load) ──
        if poll_count % 3 == 0:
            standings = fetch_standings()

            all_standings = []
            for entry in standings:
                record = parse_standing(entry)
                if record:
                    all_standings.append(record)

            if all_standings:
                producer.send(
                    topic=TOPIC_STANDINGS,
                    key="full_table",  # overwrite entire standings with each record
                    value=all_standings,
                )
                print(f"  [standings] Published {len(standings)} team records")

        producer.flush()
        print(f"  Sleeping {POLL_INTERVAL}s...\n")

        try:
            cursor.execute("""
                INSERT INTO pipeline_metadata (key, value, last_updated)
                VALUES ('last_poll', %s, NOW())
                ON CONFLICT (key) DO UPDATE SET 
                    value = EXCLUDED.value, 
                    last_updated = NOW()
            """, (datetime.now(timezone.utc).isoformat(),))
            conn.commit()

        except psycopg2.OperationalError:
            print(f"[producer] Lost database connection, reconnecting...")
            conn = get_db()
            cursor = conn.cursor()

        except Exception as e:
            print(f"[producer] Error updating metadata: {e}")
            conn.rollback()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
