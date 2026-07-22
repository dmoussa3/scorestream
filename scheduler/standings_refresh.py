from datetime import datetime, timedelta
import requests
import psycopg2
import boto3
import json
import os

def get_rds_credentials():
    client = boto3.client('secretsmanager', region_name='us-east-1')
    secret = client.get_secret_value(SecretId='scorestream/rds-credentials')
    return json.loads(secret['SecretString'])

ESPN_BASE = "https://site.api.espn.com/apis/v2/sports/soccer"

LEAGUES = {
    'epl': 'eng.1',
    'laliga': 'esp.1',
    'bundesliga': 'ger.1',
    'seriea': 'ita.1',
    'ligue1': 'fra.1',
    'worldcup': 'fifa.world'
}

CURRENT_SEASON = 2026

def fetch_standings(league_name: str, league_id: str):
    url = f"{ESPN_BASE}/{league_id}/standings"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        
        # Process data and push to XCom for the next task
        standings = []

        for group in resp.json().get('children', []):
            name = group.get('name', '')
            print(f"[airflow] Found group: {name}")  # ← debug
            for entry in group.get('standings', {}).get('entries', []):
                entry['_group_name'] = name  # Add group name to each entry for context
                standings.append(entry)
        return standings
    except requests.RequestException as e:
        print(f"[airflow] Error fetching standings for {league_name}: {e}")
        return []

def parse_standings(entry: dict, league_name: str):
    try:
        stats = {s['name']: s['value'] for s in entry.get('stats', []) if 'value' in s}
        team = entry['team']
        note = entry.get('note', {})

        logos = team.get('logos', [])
        logo_url = logos[0]['href'] if logos else None

        return {
            'team_id': team['id'],
            'league': league_name,
            'season': CURRENT_SEASON,
            'team_name': team['displayName'],
            'group_name': entry.get('_group_name', None),
            'wins': int(stats.get('wins', 0)),
            'losses': int(stats.get('losses', 0)),
            'draws': int(stats.get('ties', 0)),
            'points': int(stats.get('points', 0)),
            'goals_for': int(stats.get('pointsFor', 0)),
            'goals_against': int(stats.get('pointsAgainst', 0)),
            'goal_diff': int(stats.get('pointDifferential', 0)),
            'matches_played': int(stats.get('gamesPlayed', 0)),
            "rank": int(stats.get("rank", 0)),
            'deductions': int(stats.get('deductions', 0)),
            'note': note.get('description', None),
            'logo_url': logo_url,
            'note_color': note.get('color', None) 
        }
    except (KeyError, ValueError) as e:
        print(f"Error parsing standings entry: {e}")
        return None
    
def refresh_all_standings(conn):
    cursor = conn.cursor()
    total = 0

    try:
        for league_key, sport_path in LEAGUES.items():
            entries = fetch_standings(league_key, sport_path)
            if not entries:
                print(f"[airflow] No standings data for {league_key} — skipping")
                continue

            records = [parse_standings(e, league_key) for e in entries]
            records = [r for r in records if r is not None]

            current = [r['team_id'] for r in records]

            if current:
                cursor.execute("""
                    DELETE FROM standings
                    WHERE league = %s AND season = %s AND team_id NOT IN %s
                """, (league_key, CURRENT_SEASON, tuple(current)))
                print(f"[airflow] {league_key}: deleted {cursor.rowcount} teams not in current standings")

            for record in records:
                cursor.execute("""
                    INSERT INTO standings (
                        team_id, league, season, team_name, group_name, wins, draws, losses,
                        points, goals_for, goals_against, goal_diff,
                        matches_played, rank, note, note_color, logo_url, deductions, last_updated
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (team_id, league, season) DO UPDATE SET
                        group_name     = EXCLUDED.group_name,
                        wins           = EXCLUDED.wins,
                        draws          = EXCLUDED.draws,
                        losses         = EXCLUDED.losses,
                        points         = EXCLUDED.points,
                        goals_for      = EXCLUDED.goals_for,
                        goals_against  = EXCLUDED.goals_against,
                        goal_diff      = EXCLUDED.goal_diff,
                        matches_played = EXCLUDED.matches_played,
                        rank           = EXCLUDED.rank,
                        note           = EXCLUDED.note,
                        note_color     = EXCLUDED.note_color,
                        logo_url       = EXCLUDED.logo_url,
                        deductions     = EXCLUDED.deductions,
                        last_updated   = NOW()
                """, (
                    record["team_id"],
                    record["league"],
                    record["season"],
                    record["team_name"],
                    record["group_name"],
                    record["wins"],
                    record["draws"],
                    record["losses"],
                    record["points"],
                    record["goals_for"],
                    record["goals_against"],
                    record["goal_diff"],
                    record["matches_played"],
                    record["rank"],
                    record["note"],
                    record["note_color"],
                    record["logo_url"],
                    record["deductions"]
                ))
            
            total += len(records)
            print(f"[airflow] {league_key}: upserted {len(records)} teams")

        conn.commit()
        print(f"[airflow] Standings refresh complete — {total} total records")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

def main():
    creds = get_rds_credentials()
    conn = psycopg2.connect(
        host=creds['host'],
        database=creds['dbname'],
        user=creds['username'],
        password=creds['password'],
        port=int(creds['port'])
    )

    try:
        refresh_all_standings(conn)
    finally:
        conn.close()

if __name__ == "__main__":
    main()