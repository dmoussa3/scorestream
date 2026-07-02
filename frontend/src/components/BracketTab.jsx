import { useState, useEffect, useCallback } from "react";

const API = process.env.REACT_APP_API_URL || "http://localhost:8000";

const ROUNDS = ['Round of 32', 'Round of 16', 'Quarterfinals', 'Semifinals', 'Finals'];

const toUtcDate = (dateStr) => {
    if (!dateStr) return null
    // PostgreSQL returns '+00' but JavaScript needs '+00:00' or 'Z'
    // Replace '+00' at end with 'Z' for valid ISO format
    const normalized = dateStr
        .replace(' ', 'T')        // '2026-06-14 23:00:00+00' → '2026-06-14T23:00:00+00'
        .replace(/\+00$/, 'Z')    // '+00' at end → 'Z'
        .replace(/\+00:00$/, 'Z') // '+00:00' at end → 'Z'
    return new Date(normalized)
}

function BracketCard({ game, theme }) {
    const homeWon = game.home_score > game.away_score || (game.shootout_home != null &&game.shootout_home > game.shootout_away);
    const awayWon = game.away_score > game.home_score || (game.shootout_away != null && game.shootout_away > game.shootout_home);

    const isFinished = ['STATUS_FINAL_AET', 'STATUS_FINAL_PEN', 'STATUS_FULL_TIME'].includes(game.status);

    const TeamRow = ({ name, teamId, score, shootout, won }) => (
        <div
            className="flex items-center justify-between gap-2 px-3 py-2"
            style={{
                backgroundColor: won && isFinished ? `${theme.accent}22` : 'transparent',
                borderLeft: won && isFinished ? `3px solid ${theme.accent}` : '3px solid transparent',
            }}
        >
            <div className="flex items-center gap-2 min-w-0">
                <div className="w-6 h-6 rounded-full bg-white flex items-center justify-center flex-shrink-0">
                    <img
                        src={`https://a.espncdn.com/i/teamlogos/soccer/500/${teamId}.png`}
                        alt={name}
                        className="w-5 h-5 object-contain"
                        onError={(e) => { e.target.style.display = 'none' }}
                    />
                </div>
                <span
                    className={`text-xs truncate ${won && isFinished ? 'font-bold' : 'font-medium'}`}
                    style={{ color: won && isFinished ? theme.accent : 'white' }}
                >
                    {name}
                </span>
            </div>
            <span className="text-xs text-white font-semibold flex-shrink-0">
                {isFinished ? score : ''}
                {shootout != null && (
                    <span className="opacity-60"> ({shootout})</span>
                )}
            </span>
        </div>
    )

    return (
        <div
            style={{ backgroundColor: theme.secondary, borderColor: theme.border }}
            className="border rounded-lg overflow-hidden w-48 flex-shrink-0"
        >
            <TeamRow
                name={game.home_team_name}
                teamId={game.home_id}
                score={game.home_score}
                shootout={game.shootout_home}
                won={homeWon}
            />
            <div style={{ borderColor: theme.border }} className="border-t" />
            <TeamRow
                name={game.away_team_name}
                teamId={game.away_id}
                score={game.away_score}
                shootout={game.shootout_away}
                won={awayWon}
            />
            {!isFinished && (
                <div className="px-3 py-1 text-center text-xs border-t" style={{ borderColor: theme.border, color: theme.accent, opacity: 0.7 }}>
                    {toUtcDate(game.start_time)?.toLocaleDateString('en-US', {
                        month: 'short', day: 'numeric',
                        hour: 'numeric', minute: '2-digit',
                        timeZone: 'America/New_York',
                    })}
                </div>
            )}
        </div>
    )
}

export default function BracketTab({ theme, onSelectGame }) {
    const [games, setGames] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const fetchBracket = useCallback(async () => {
        try {
            const res = await fetch(`${API}/games?league=worldcup`);
            const data = await res.json();
            setGames(data.filter(g => g.round));
            setLoading(false);
        } catch (err) {
            setError(err.message || 'Error fetching bracket data');
            setLoading(false);
        }
    }, [])

    useEffect(() => {
        fetchBracket();
    }, [fetchBracket])

    useEffect(() => {
        const interval = setInterval(fetchBracket, 60000); // Refresh every 60 seconds
        return () => clearInterval(interval);
    }, [fetchBracket]);

    if (loading) return <div className="p-4" style={{ color: theme?.accent }}>Loading bracket...</div>
    if (error)   return <div className="p-4 text-red-400">Error: {error}</div>
    if (!games?.length) return (
        <div className="p-4 text-center" style={{ color: theme?.accent }}>
            The knockout stage hasn't started yet.
        </div>
    )

    const byRound = games.reduce((acc, game) => {
        if (!acc[game.round]) acc[game.round] = [];
        acc[game.round].push(game);
        return acc;
    }, {})

    Object.keys(byRound).forEach(round => {
        byRound[round].sort((a,b) => toUtcDate(a.start_time) - toUtcDate(b.start_time))
    })

    const third = byRound['Third Place'] || [];

    const getWinner = (game) => {
        const finished = ['STATUS_FINAL_AET', 'STATUS_FINAL_PEN', 'STATUS_FULL_TIME'].includes(game.status);
        if (!finished) return null;
        if (game.home_score > game.away_score) return game.home_team_name;
        if (game.away_score > game.home_score) return game.away_team_name;
        if (game.shootout_home != null && game.shootout_home > game.shootout_away) return game.home_team_name;
        if (game.shootout_away != null && game.shootout_away > game.shootout_home) return game.away_team_name;
        return null;
    }

    const reorderbyRound = (rounds) => {
        for (let i = ROUNDS.length - 1; i >= 1; i--) {
            const laterRound = byRound[ROUNDS[i]];
            const earlierRound = byRound[ROUNDS[i - 1]];
            if (!laterRound || !earlierRound) continue;

            const ordered = []
            const used = new Set();

            laterRound.forEach(nextGame => {
                const feeders = earlierRound.filter(g => {
                    const winner = getWinner(g);
                    return winner && (winner === nextGame.home_team_name || winner === nextGame.away_team_name);
                })

                feeders.sort((a,b) => {
                    const aWinner = getWinner(a) === nextGame.home_team_name ? 0 : 1;
                    const bWinner = getWinner(b) === nextGame.home_team_name ? 0 : 1;
                    return aWinner - bWinner;
                })

                feeders.forEach(f => {
                    if (!used.has(f.game_id)) {
                        ordered.push(f);
                        used.add(f.game_id);
                    }
                })
            })

            earlierRound.forEach(g => {
                if (!used.has(g.game_id)) ordered.push(g);
            })
            byRound[ROUNDS[i - 1]] = ordered;
        }
        return byRound
    }

    reorderbyRound(byRound);

    return (
        <div className="w-full">

            {/* Horizontally scrollable bracket columns */}
            <div className="overflow-x-auto pb-4">
                <div className="flex gap-8 min-w-max px-2">
                    {ROUNDS.map(round => (
                        byRound[round]?.length > 0 && (
                            <div key={round} className="flex flex-col">
                                <h3
                                    className="text-xs font-bold uppercase tracking-wider mb-3 text-center"
                                    style={{ color: theme.accent }}
                                >
                                    {round}
                                </h3>
                                {/* justify-around spreads later-round games vertically 
                                    so they align between their feeder games */}
                                <div className="flex flex-col justify-around gap-3 flex-1">
                                    {byRound[round].map(game => (
                                        <div
                                            key={game.game_id}
                                            onClick={() => onSelectGame?.(game.game_id)}
                                            className="cursor-pointer hover:opacity-80 transition-opacity"
                                        >
                                            <BracketCard game={game} theme={theme} />
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )
                    ))}
                </div>
            </div>

            {/* Third place match — shown separately below */}
            {third?.length > 0 && (
                <div className="mt-6">
                    <h3
                        className="text-xs font-bold uppercase tracking-wider mb-3"
                        style={{ color: theme.accent }}
                    >
                        Third Place Match
                    </h3>
                    <div
                        onClick={() => onSelectGame?.(third[0].game_id)}
                        className="cursor-pointer hover:opacity-80 transition-opacity inline-block"
                    >
                        <BracketCard game={third[0]} theme={theme} />
                    </div>
                </div>
            )}
        </div>
    )
}