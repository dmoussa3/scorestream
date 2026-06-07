import os
import requests
from datetime import datetime
import time
import psycopg2

API_KEY = os.getenv("FOOTBALL_DATA_ORG_API_KEY")
if not API_KEY:
    raise RuntimeError("FOOTBALL_DATA_ORG_API_KEY environment variable not set")

DB_URL = os.getenv("DATABASE_URL", "postgresql://admin:password@postgres:5432/scorestream")
BASE_URL = "https://api.football-data.org/v4"

# Map of league codes to their corresponding API identifiers
LEAGUES = {
    "PL": "epl",
    "BL1": "bundesliga",
    "SA": "seriea",
    "PD": "laliga",
    "FL1": "ligue1",
}

# Map of league codes to their corresponding database IDs
ID = {
    "PL": 2021,
    "BL1": 2002,
    "SA": 2019,
    "PD": 2014,
    "FL1": 2015,
}

# Map of API status codes to our internal status values
STATUS_MAP = {
    "FINISHED":   "STATUS_FULL_TIME",
    "IN_PLAY":    "STATUS_IN_PROGRESS",
    "PAUSED":     "STATUS_HALFTIME",
    "SCHEDULED":  "STATUS_SCHEDULED",
    "TIMED":      "STATUS_SCHEDULED",
    "POSTPONED":  "STATUS_POSTPONED",
    "CANCELLED":  "STATUS_CANCELLED",
    "ABANDONED":  "STATUS_ABANDONED",
}

def fetch_matches(competition_code: str, season:int):
    competition_id = ID[competition_code]
    url = f"{BASE_URL}/competitions/{competition_id}/matches"
    params = {"season": season}

    try:
        response = requests.get(url, headers={"X-Auth-Token": API_KEY}, params=params, timeout=10)
        response.raise_for_status()
        data = response.json().get("matches", [])
        print(f"Fetched {len(data)} matches for {competition_code} {season}")
        return data
    except Exception as e:
        print(f"Error fetching matches for {competition_code} {season}: {e}")
        return []
    
def parse_match(match: dict, league_key: str) -> dict | None:
    """Converts football-data.org into ScoreStream schema"""

    try:
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}

        score = match.get("score", {})
        full_time = score.get("fullTime", {})
        status_raw = match.get("status", "SCHEDULED")

        # Avoid ID conflicts with existing matches from ESPN API by prefixing with 'fd_' and using the football-data.org match ID
        game_id = f"fd_{match['id']}"

        home_score = full_time.get("home") or 0
        away_score = full_time.get("away") or 0

        matchday = match.get("matchday", 0)

        return {
            "game_id":        game_id,
            "league":         league_key,
            "home_team":      home.get("tla") or "UNK",
            "away_team":      away.get("tla") or "UNK",
            "home_team_name": home.get("name") or "Unknown",
            "away_team_name": away.get("name") or "Unknown",
            "home_id":        str(home.get("id", "")),
            "away_id":        str(away.get("id", "")),
            "home_score":     int(home_score),
            "away_score":     int(away_score),
            "status":         STATUS_MAP.get(status_raw, "STATUS_UNKNOWN"),
            "status_detail":  status_raw,
            "period":         2 if status_raw == "FINISHED" else 0,
            "clock":          "",
            "start_time":     match.get("utcDate", ""),
            "matchday":       matchday,
        }
    except Exception as e:
        print(f"Error parsing match data {match.get('id')}: {e}")
        return None
    
def fetch_scorers(competition_code: str, season: int):
    competition_id = ID[competition_code]
    url = f"{BASE_URL}/competitions/{competition_id}/scorers"
    params = {"season": season, "limit": 50}  # Fetch top 50 scorers to ensure we get all relevant data for backfilling

    try:
        response = requests.get(url, headers={"X-Auth-Token": API_KEY}, params=params, timeout=10)
        response.raise_for_status()
        data = response.json().get("scorers", [])
        print(f"Fetched {len(data)} scorers for {competition_code} {season}")
        return data
    except Exception as e:
        print(f"Error fetching scorers for {competition_code} {season}: {e}")
        return []
    
def backfill_games(season: int = 2025):
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()
    total = 0

    print(f"Backfilling games for the {season}/{season+1} season...")

    for comp_code, league_key in LEAGUES.items():
        print(f"Processing {comp_code} ({league_key})...")
        matches = fetch_matches(comp_code, season)

        for match in matches:
            parsed_match = parse_match(match, league_key)

            if parsed_match:
                try:            
                    cursor.execute("""
                        INSERT INTO games (
                            game_id, league, home_team, home_team_name, home_id, away_team,
                            away_team_name, away_id,
                            home_score, away_score, period, clock, status, status_detail,
                            start_time, matchday, last_updated
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (game_id) DO UPDATE SET
                            home_score    = EXCLUDED.home_score,
                            away_score    = EXCLUDED.away_score,
                            status        = EXCLUDED.status,
                            status_detail = EXCLUDED.status_detail,
                            last_updated  = NOW()
                    """, (
                        parsed_match["game_id"],
                        parsed_match["league"],
                        parsed_match["home_team"],
                        parsed_match["home_team_name"],
                        parsed_match["home_id"], 
                        parsed_match["away_team"],
                        parsed_match["away_team_name"],
                        parsed_match["away_id"],
                        parsed_match["home_score"],    
                        parsed_match["away_score"],
                        parsed_match["period"],        
                        parsed_match["clock"],
                        parsed_match["status"],        
                        parsed_match["status_detail"],
                        parsed_match["start_time"],
                        parsed_match["matchday"],
                    ))
                    total+=1
                except Exception as e:
                    print(f"Error inserting match {parsed_match['game_id']}: {e}")
                    conn.rollback()
            
        conn.commit()
        print(f"Finished processing {comp_code}, {len(matches)} matches. Total matches backfilled so far: {total}")
        time.sleep(6)

    cursor.close()
    conn.close()
    print(f"Backfilling complete. Total matches backfilled: {total}")

def backfill_stats(season: int = 2025):
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()
    total = 0

    # Create table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS season_stats (
            player_id     VARCHAR,
            player_name   VARCHAR,
            team_id       VARCHAR,
            team_name     VARCHAR,
            league        VARCHAR,
            season        INTEGER,
            goals         INTEGER DEFAULT 0,
            assists       INTEGER DEFAULT 0,
            penalties     INTEGER DEFAULT 0,
            last_updated  TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (player_id, league, season)
        )
    """)
    conn.commit()

    print(f"Backfilling stats for the {season}/{season+1} season...")

    for comp_code, league_key in LEAGUES.items():
        print(f"Processing stats for {comp_code} ({league_key})...")
        scorers = fetch_scorers(comp_code, season)

        for scorer in scorers:
            player = scorer.get("player", {})
            team = scorer.get("team", {})

            cursor.execute("""
                INSERT INTO season_stats (
                    player_id, player_name, team_id, team_name,
                    league, season, goals, assists, penalties, last_updated
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (player_id, league, season) DO UPDATE SET
                    goals        = EXCLUDED.goals,
                    assists      = EXCLUDED.assists,
                    penalties    = EXCLUDED.penalties,
                    last_updated = NOW()
            """, (
                f"fd_{player.get('id')}",
                player.get("name"),
                f"fd_{team.get('id')}",
                team.get("name"),
                league_key,
                season,
                scorer.get("goals", 0),
                scorer.get("assists", 0),
                scorer.get("penalties", 0),
            ))
            total += 1

        conn.commit()
        print(f"Finished processing stats for {comp_code}, {len(scorers)} entries. Total stats entries backfilled so far: {total}")
        time.sleep(6)

    cursor.close()
    conn.close()
    print(f"Stats backfilling complete. Total entries inserted: {total}")

if __name__ == "__main__":
    backfill_games(season=2025)
    backfill_stats(season=2025)