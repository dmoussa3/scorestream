"""
ScoreStream — ESPN Soccer Producer
Polls the ESPN public API every N seconds and publishes game events to Kafka.
"""

import json
import os
import time
import signal
import sys
from datetime import datetime, timedelta, timezone
import psycopg2
from curl_cffi import requests as cffi_requests
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

# ── Config ──────────────────────────────────────────────────────────
KAFKA_SERVERS      = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
POLL_INTERVAL      = int(os.getenv("POLL_INTERVAL_SECONDS", 15))
TOPIC_SCORES       = "sports.live.scores"
TOPIC_STANDINGS    = "sports.standings"

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/soccer"

HEADERS = {"User-Agent": "ScoreStream/1.0"}

LEAGUES = {
    "epl": "eng.1",
    "laliga": "esp.1",
    "seriea": "ita.1",
    "bundesliga": "ger.1",
    "ligue1": "fra.1",
    "mls": "usa.1"
}

ROUNDS = {
    "round of 32": "Round of 32",
    "round of 16": "Round of 16",
    "quarterfinals": "Quarterfinals",
    "semifinals": "Semifinals",
    "third place": "Third Place",
    "final": "Final"
}

class MSKTokenProvider:
    """Token provider object satisfying kafka-python's OAUTHBEARER interface."""

    def __init__(self, region: str):
        self.region = region

    def token(self):
        token, expiry_ms = MSKAuthTokenProvider.generate_auth_token(self.region)
        return token
    
    def token_expiry_ms(self):
        _, expiry_ms = MSKAuthTokenProvider.generate_auth_token(self.region)
        return expiry_ms

def get_db():
    url = os.getenv("DATABASE_URL")

    ## If DATABASE_URL is not set, construct it from individual environment variables (local development only)
    if not url:
        host     = os.getenv("DB_HOST", "localhost")
        port     = os.getenv("DB_PORT", "5432")
        user     = os.getenv("DB_USER", "admin")
        password = os.getenv("DB_PASSWORD", "password")
        dbname   = os.getenv("DB_NAME", "scorestream")
        url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}?sslmode=require"
    return psycopg2.connect(url)

# ── Kafka setup ─────────────────────────────────────────────────────
def create_producer(retries: int = 10, delay: int = 5) -> KafkaProducer:
    """Retry connecting to Kafka until it's ready."""

    token_provider = MSKTokenProvider(region="us-east-1")

    for attempt in range(1, retries + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "").split(","),
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                security_protocol="SASL_SSL",
                sasl_mechanism="OAUTHBEARER",
                sasl_oauth_token_provider=token_provider,
                acks="all",               # wait for all replicas to confirm
                retries=3,
            )
            print(f"[producer] Connected to Kafka at {os.getenv('KAFKA_BOOTSTRAP_SERVERS', '')}")
            return producer
        except NoBrokersAvailable:
            print(f"[producer] Kafka not ready — attempt {attempt}/{retries}, retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError("Could not connect to Kafka after multiple attempts")

def create_topics(servers: str, region: str = "us-east-1"):
    """Create Kafka topics if they don't exist."""
    token_provider = MSKTokenProvider(region=region)

    admin_client = KafkaAdminClient(
        bootstrap_servers=servers,
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=token_provider,
    )

    topics = [
        NewTopic(name=TOPIC_SCORES, num_partitions=3, replication_factor=2),
        NewTopic(name=TOPIC_STANDINGS, num_partitions=1, replication_factor=2),
    ]

    try:
        admin_client.create_topics(new_topics=topics, validate_only=False)
        print(f"[producer] Topics created: {[t.name for t in topics]}")
    except TopicAlreadyExistsError:
        print(f"[producer] Topics already exist: {[t.name for t in topics]}")
    except Exception as e:
        print(f"[producer] Topic creation error: {e}")
    finally:
        admin_client.close()

# ── ESPN helpers ─────────────────────────────────────────────────────

def fetch_scoreboard(league: str) -> list[dict]:
    """Return list of raw game objects from ESPN scoreboard."""
    events = []

    proxy_url = f"http://{os.getenv('PROXY_USERNAME')}:{os.getenv('PROXY_PASSWORD')}@{os.getenv('PROXY_HOST', 'p.webshare.io')}:{os.getenv('PROXY_PORT', '80')}"

    for day_offset in [-7, -6, -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7]:
        date_str = (datetime.now() + timedelta(days=day_offset)).strftime("%Y%m%d")
        url = f"{ESPN_BASE}/{league}/scoreboard?dates={date_str}"

        for attempt in range(3):
            try:
                resp = cffi_requests.get(
                    url,
                    headers=HEADERS,
                    proxies={"http": proxy_url, "https": proxy_url},
                    impersonate="chrome120",
                    timeout=15,
                )

                if resp.status_code == 403:
                    wait = 2 ** attempt
                    print(f"[producer] 403 for {league} {date_str} — retrying in {wait}s (attempt {attempt + 1}/3)")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                day_events = resp.json().get("events", [])
                events.extend(day_events)
                break

            except Exception as e:
                if attempt == 2:
                    print(f"[producer] Scoreboard fetch error for {league} for {date_str}: {e}")
                else:
                    time.sleep(2 ** attempt)

        time.sleep(0.3)

    seen = set()
    unique_events = []
    for event in events:
        if event["id"] not in seen:
            unique_events.append(event)
            seen.add(event["id"])

    return unique_events

def fetch_standings(league: str) -> list[dict]:
    """Return raw standings entries from ESPN."""
    proxy_url = f"http://{os.getenv('PROXY_USERNAME')}:{os.getenv('PROXY_PASSWORD')}@{os.getenv('PROXY_HOST', 'p.webshare.io')}:{os.getenv('PROXY_PORT', '80')}"

    for attempt in range(3):
        try:
            url = f"{ESPN_STANDINGS}/{league}/standings"
            resp = cffi_requests.get(
                url,
                headers=HEADERS,
                proxies={"http": proxy_url, "https": proxy_url},
                impersonate="chrome120",
                timeout=15,
            )

            if resp.status_code == 403:
                wait = 2 ** attempt
                print(f"[producer] 403 for standings {league} — retrying in {wait}s (attempt {attempt + 1}/3)")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            entries = []

            for group in resp.json().get("children", []):
                name = group.get("name", "")
                for entry in group.get("standings", {}).get("entries", []):
                    entry["_group_name"] = name
                    entries.append(entry)

            return entries

        except Exception as e:
            if attempt == 2:
                print(f"[producer] Standings fetch error for {league}: {e}")
            else:
                time.sleep(2 ** attempt)

    return []

def parse_round(event: dict, comp: dict) -> str | None:
    """Extract a clean round name from a raw ESPN event object."""
    note = comp.get("altGameNote", "") or ""  # Fallback to empty string if not present

    if not note:
        notes = comp.get("notes", [])
        note = notes[0].get("headline", "") if notes else ""

    note_lower = note.lower()
    for key, value in ROUNDS.items():
        if key in note_lower:
            if key == "final" and ("quarterfinal" in note_lower or "semifinal" in note_lower):
                continue  # Avoid mislabeling quarterfinals/semifinals as finals
            return value
    return None

def parse_game(game: dict, league: str) -> dict | None:
    """Extract a clean game event from a raw ESPN event object."""

    try:
        competition = game["competitions"][0]
        competitors  = competition["competitors"]
        home = next(t for t in competitors if t["homeAway"] == "home")
        away = next(t for t in competitors if t["homeAway"] == "away")
        status =  competition["status"]
        home_logos = home.get("team", {}).get("logos", [])
        away_logos = away.get("team", {}).get("logos", [])
        shootout_home = home.get("shootoutScore", None)
        shootout_away = away.get("shootoutScore", None)

        goals = []
        for detail in competition.get("details", []):
            if not detail.get("scoringPlay", False):
                continue

            clock_value = int(detail.get("clock", {}).get("value", 0))
            if detail.get("shootout") or (
                clock_value >= 7200 and status["type"]["name"] in ("STATUS_FINAL_PEN", "STATUS_PENALTIES")
            ):
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
                "penalty_goal": detail.get("penaltyKick", False),
                "league": league,
            })

        cards = []
        for detail in competition.get("details", []):
            if detail.get("scoreValue", False):
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
            "league":     league,
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
            "shootout_home": shootout_home,
            "shootout_away": shootout_away,
            "round": parse_round(game, competition) if league == "worldcup" else None,
            "period":    status.get("period", 0),
            "clock":     status.get("displayClock", ""),
            "home_logo": home_logos[0]["href"] if home_logos else None,
            "away_logo": away_logos[0]["href"] if away_logos else None,
            "goals":     goals,
            "cards":     cards,
            "start_time": game.get("date"),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
    except (KeyError, StopIteration) as e:
        print(f"[producer] Could not parse game {game.get('id')}: {e}")
        return None


def parse_standing(entry: dict, league: str) -> dict | None:
    """Extract a clean standing record from a raw ESPN standings entry."""
    try:
        stats = {s["name"]: s["value"] for s in entry.get("stats", []) if "value" in s}
        team  = entry["team"]
        note  = entry.get("note", {})
        logos = team.get("logos", [])
        logo_url = logos[0]["href"] if logos else None

        return {
            "team_id": team["id"],
            "league": league,
            "team_name": team["displayName"],
            "group_name": entry.get("_group_name", None),
            "wins": int(stats.get("wins", 0)),
            "draws": int(stats.get("ties", 0)),
            "losses": int(stats.get("losses", 0)),
            "points": int(stats.get("points", 0)),
            "goals_for": int(stats.get("pointsFor", 0)),
            "goals_against": int(stats.get("pointsAgainst", 0)),
            "goal_diff": int(stats.get("pointDifferential", 0)),
            "matches_played": int(stats.get("gamesPlayed", 0)),
            "rank": int(stats.get("rank", 0)),
            "deductions": int(stats.get("deductions", 0)),
            "note": note.get("description", None),
            "note_color": note.get("color", None),
            "logo_url": logo_url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except (KeyError, TypeError) as e:
        print(f"[producer] Could not parse standing: {e}")
        return None


# ── Main loop ────────────────────────────────────────────────────────
def run():    
    producer = create_producer()

    def handle_shutdown(signum, frame):
        print(f"[producer] Received signal {signum}, shutting down...")
        try:
            producer.flush(timeout=10)
            producer.close()
        except Exception as e:
            pass
        sys.exit(0)
    
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    print("[producer] Creating Kafka topics if they don't exist...")
    create_topics(KAFKA_SERVERS)

    poll_count = 0

    conn = get_db()
    cursor = conn.cursor()

    while True:
        poll_count += 1
        print(f"[producer] ── Poll #{poll_count} @ {datetime.now().strftime('%H:%M:%S')} ──")

        # ── Scores — fetch all leagues concurrently ──
        def fetch_and_publish_scores(args):
            league_name, league_id = args
            games = fetch_scoreboard(league_id)
            published = 0
            events = []
            for game in games:
                event = parse_game(game, league_name)
                if event:
                    events.append((event["game_id"], event))
                    published += 1
            return league_name, events, published

        all_score_events = []
        with ThreadPoolExecutor(max_workers=len(LEAGUES)) as executor:
            futures = {
                executor.submit(fetch_and_publish_scores, item): item
                for item in LEAGUES.items()
            }
            for future in as_completed(futures):
                try:
                    league_name, events, published = future.result()
                    all_score_events.extend(events)
                    print(f"  [{league_name}] {published} games published")
                except Exception as e:
                    league_name = futures[future][0]
                    print(f"  [{league_name}] Error: {e}")

        # Publish all score events after all fetches complete
        for game_id, event in all_score_events:
            producer.send(
                topic=TOPIC_SCORES,
                key=game_id,
                value=event,
            )

        # ── Standings — fetch all leagues concurrently (every 3 polls) ──
        if poll_count % 3 == 0:
            def fetch_and_parse_standings(args):
                league_name, league_id = args
                standings = fetch_standings(league_id)
                all_standings = []
                for entry in standings:
                    record = parse_standing(entry, league_name)
                    if record:
                        all_standings.append(record)
                return league_name, all_standings

            with ThreadPoolExecutor(max_workers=len(LEAGUES)) as executor:
                futures = {
                    executor.submit(fetch_and_parse_standings, item): item
                    for item in LEAGUES.items()
                }
                for future in as_completed(futures):
                    try:
                        league_name, all_standings = future.result()
                        if all_standings:
                            producer.send(
                                topic=TOPIC_STANDINGS,
                                key=f"{league_name}_standings",
                                value=all_standings,
                            )
                            print(f"  [standings] {league_name}: Published {len(all_standings)} team records")
                    except Exception as e:
                        league_name = futures[future][0]
                        print(f"  [standings] {league_name} Error: {e}")

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
