import { useEffect, useRef, useState, useCallback } from "react";

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000'

const LIVE_STATUSES = ['STATUS_IN_PROGRESS', 'STATUS_HALFTIME', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF']
const FINAL_STATUSES = ['STATUS_FULL_TIME', 'STATUS_FINAL_PEN', 'STATUS_FINAL_AET']

const parseClock = (clockStr, period, status) => {
    if (status === 'STATUS_HALFTIME') return 2700
    if (!clockStr) return period === 1 ? 0 : 2700
    const parts = clockStr.replace(/'/g, '').split('+')
    const base = parseInt(parts[0]) || 0
    const extra = parseInt(parts[1]) || 0
    return (base + extra) * 60
}

const getCapSeconds = (period, clockStr, status) => {
    if (!clockStr || status === 'STATUS_HALFTIME') {
        return period === 1 ? 2700 : period === 2 ? 5450 : 7500
    }
    const parts = clockStr.replace(/'/g, '').split('+')
    const base = parseInt(parts[0]) || 0
    const extra = parseInt(parts[1]) || 0
    const total = (base + extra) * 60
    if (period >= 3) return Math.max(total + 300, 7500)
    if (period === 2) return Math.max(total + 300, 5450)
    return Math.max(total + 300, 2700)
}

const GOAL_ICON = {
    'Goal': '⚽',
    'Goal - Volley': '⚽',
    'Penalty - Scored': '🎯',
    'Goal - Header': '⚽',
    'Goal - Free-kick': '🎯',
}

const DEFAULT_THEME = {
    primary: '#37003c',
    secondary: '#2d0032',
    accent: '#00ff85',
    border: '#5f0068',
    text: '#00ff85',
}

export default function MatchesTab({ gameId, onBack, theme = DEFAULT_THEME, league, lastUpdate }) {
    const [game, setGame] = useState(null)
    const [goals, setGoals] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    const isUpcoming = game != null && !LIVE_STATUSES.includes(game.status) && !FINAL_STATUSES.includes(game.status)

    const fetchGame = useCallback(async () => {
        try {
            const res = await fetch(`${API}/games/${gameId}`)
            const data = await res.json()
            setGame(data)
            setError(null)
        } catch (err) {
            setError(err.message)
        } finally {
            setLoading(false)
        }
    }, [gameId])

    const fetchGoals = useCallback(async () => {
        if (!game || isUpcoming) return
        try {
            const res = await fetch(`${API}/games/${gameId}/stats`)
            const data = await res.json()
            setGoals(Array.isArray(data) ? data : [])
        } catch (err) {
            console.error('Goals fetch error:', err)
        }
    }, [gameId, game, isUpcoming])

    // Initial fetch
    useEffect(() => { fetchGame() }, [fetchGame])
    useEffect(() => { fetchGoals() }, [fetchGoals])

    // Interval polling
    useEffect(() => {
        const interval = setInterval(fetchGame, 15000)
        return () => clearInterval(interval)
    }, [fetchGame])

    useEffect(() => {
        const interval = setInterval(fetchGoals, 15000)
        return () => clearInterval(interval)
    }, [fetchGoals])

    // WebSocket push trigger
    useEffect(() => {
        if (!lastUpdate) return
        if (lastUpdate.type === 'scores') {
            fetchGame()
            fetchGoals()
        }
    }, [lastUpdate, fetchGame, fetchGoals])

    const [elapsedSeconds, setElapsedSeconds] = useState(0)
    const lastSyncedRef = useRef(null)
    const baseSecondsRef = useRef(0)

    useEffect(() => {
        if (!game?.clock || !LIVE_STATUSES.includes(game?.status ?? '')) return
        const total = parseClock(game.clock, game.period, game.status)
        baseSecondsRef.current = total
        lastSyncedRef.current = Date.now()
    }, [game?.clock, game?.status, game?.period])

    useEffect(() => {
        if (!LIVE_STATUSES.includes(game?.status ?? '')) return
        const timer = setInterval(() => {
            if (lastSyncedRef.current === null) return
            const elapsedSinceSync = (Date.now() - lastSyncedRef.current) / 1000
            const interpolated = baseSecondsRef.current + elapsedSinceSync
            const cap = getCapSeconds(game?.period, game?.clock, game?.status)
            setElapsedSeconds(Math.min(interpolated, cap))
        }, 1000)
        return () => clearInterval(timer)
    }, [game?.status, game?.period])

    if (!gameId) return <div className="text-red-400 p-4">Please select a game from the Scores tab to view details.</div>
    if (loading) return <div className="p-4" style={{ color: theme?.accent }}>Loading match details...</div>
    if (error) return <div className="p-4 text-red-400">Error: {error}</div>
    if (!game) return <div className="text-red-400 p-4">Game not found.</div>

    const goalsArray = goals

    const extraTime =
        game.period >= 3 ||
        ['STATUS_FIRST_EXTRA', 'STATUS_SECOND_EXTRA', 'STATUS_PENALTIES'].includes(game.status) ||
        FINAL_STATUSES.includes(game.status) && goalsArray.some(g => g.seconds > 5450)

    const MATCH_DURATION = extraTime ? 7500 : 5450
    const HALFTIME_DURATION = 2700
    const FULLTIME_DURATION = 5450
    const ET_HALF = 6300
    const ET_END = 7200

    const getTimelinePosition = (currentSeconds) => {
        const percentage = (currentSeconds / MATCH_DURATION) * 100
        return Math.min(percentage, 99)
    }

    const secondsDisplay = (seconds, period) => {
        const mins = Math.floor(seconds / 60)
        if (mins > 90) return `90'+${mins - 90}'`
        if (mins >= 45 && period === 1) return `45'+${mins - 45}'`
        return `${mins}'`
    }

    const isLive = game && LIVE_STATUSES.includes(game.status)
    const livePercentage = Math.min((elapsedSeconds / MATCH_DURATION) * 100, 99)

    const homeGoals = goalsArray.filter(g => g.team_id === game.home_id)
    const awayGoals = goalsArray.filter(g => g.team_id === game.away_id)

    const cleanName = (name) => {
        if (!name) return 'Unknown'
        return name
            .replace(/\s+null\s*/gi, '')
            .replace(/null\s+/gi, '')
            .trim()
    }

    function TeamLogo({ teamId, team, size = 16, isNational = false }) {
        const [imgSrc, setImgSrc] = useState(
            `https://a.espncdn.com/i/teamlogos/soccer/500/${teamId}.png`
        )
        const attemptedFallback = useRef(false)

        const handleError = () => {
            if (attemptedFallback.current || !isNational) {
                setImgSrc(null)
                return
            }
            attemptedFallback.current = true
            setImgSrc(
                `https://a.espncdn.com/i/teamlogos/countries/500/${team?.toLowerCase().replace(/ /g, '-')}.png`
            )
        }

        if (!imgSrc) return (
            <div className="w-16 h-16 rounded-full bg-white flex items-center justify-center flex-shrink-0" />
        )

        return (
            <div className="w-18 h-18 rounded-full flex items-center justify-center flex-shrink-0">
                <div className="w-20 h-20 rounded-full bg-white flex items-center justify-center flex-shrink-0">
                    <img
                        src={imgSrc}
                        alt={team}
                        className={`w-${size} h-${size} object-contain`}
                        onError={handleError}
                    />
                </div>
            </div>
        )
    }

    return (
        <div className="max-w-4xl mx-auto space-y-6">

            {/* Back button */}
            <button
                onClick={onBack}
                style={{ backgroundColor: theme.accent, color: theme.primary }}
                className="flex items-center gap-2 text-sm rounded-lg p-2 transition-colors"
                onMouseEnter={e => {
                    e.currentTarget.style.backgroundColor = theme.primary
                    e.currentTarget.style.color = theme.accent
                    e.currentTarget.style.outline = `2px solid ${theme.accent}`
                }}
                onMouseLeave={e => {
                    e.currentTarget.style.backgroundColor = theme.accent
                    e.currentTarget.style.color = theme.primary
                    e.currentTarget.style.outline = 'none'
                }}
            >
                ← Back to Scores
            </button>

            {/* Match header card */}
            <div
                style={{ backgroundColor: theme.secondary, borderColor: theme.border }}
                className="border rounded-lg p-6"
            >
                {/* Status */}
                <div
                    className="text-center text-sm mb-4 uppercase tracking-wider"
                    style={{ color: theme.accent }}
                >
                    {isLive ? secondsDisplay(elapsedSeconds, game?.period) : game.status_detail}
                </div>

                {/* Score row */}
                <div className="grid grid-cols-3 items-center gap-4">

                    {/* Home team */}
                    <div className="flex flex-col items-end">
                        <div className="flex items-center gap-3">
                            <div className="text-2xl font-bold text-white text-center">
                                {game.home_team_name || game.home_team}
                            </div>
                            <TeamLogo
                                teamId={game.home_id}
                                team={game.home_team}
                                isNational={game.league === 'worldcup'}
                            />
                        </div>
                    </div>

                    {/* Score */}
                    <div className="text-center">
                        <div className="text-5xl font-bold text-white tracking-tight">
                            {game.shootout_home ? `(${game.shootout_home})` : ``} {game.home_score} – {game.away_score} {game.shootout_away ? `(${game.shootout_away})` : ``}
                        </div>
                    </div>

                    {/* Away team */}
                    <div className="flex flex-col items-start">
                        <div className="flex items-center gap-3">
                            <TeamLogo
                                teamId={game.away_id}
                                team={game.away_team}
                                isNational={game.league === 'worldcup'}
                            />
                            <div className="text-2xl font-bold text-white text-center">
                                {game.away_team_name || game.away_team}
                            </div>
                        </div>
                    </div>

                </div>

                {(homeGoals.length > 0 || awayGoals.length > 0) && (
                    <div className="grid grid-cols-3 gap-4 pt-4 text-center">
                        <div className="space-y-1">
                            {homeGoals.map((g, i) => (
                                <div key={i} className="text-xs" style={{ color: theme.accent, opacity: 0.8 }}>
                                    {GOAL_ICON[g.goal_type] || '⚽'} {cleanName(g.player_name)} {g.own_goal && '(OG)'} {g.penalty_goal && '(P)'} {g.minute}
                                </div>
                            ))}
                        </div>
                        <div />
                        <div className="space-y-1">
                            {awayGoals.map((g, i) => (
                                <div key={i} className="text-xs" style={{ color: theme.accent, opacity: 0.8 }}>
                                    {GOAL_ICON[g.goal_type] || '⚽'} {cleanName(g.player_name)} {g.own_goal && '(OG)'} {g.penalty_goal && '(P)'} {g.minute}
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* Goal timeline */}
            {(isLive || goalsArray.length > 0) && (
                <div
                    className="border rounded-lg p-6"
                    style={{ borderColor: theme.border, backgroundColor: theme.secondary }}
                >
                    <h3 className="text-sm font-semibold text-white mb-6 uppercase tracking-wider">
                        Goal Timeline
                    </h3>

                    <div className="flex gap-6">
                        <div className="flex-1">

                            {/* Minute labels above bar */}
                            <div
                                className="relative text-xs mb-2 h-4"
                                style={{ color: theme.accent }}
                            >
                                <span className="absolute left-0">0'</span>
                                <span
                                    className="absolute -translate-x-1/2"
                                    style={{ left: `${(HALFTIME_DURATION / MATCH_DURATION) * 100}%` }}
                                >
                                    HT
                                </span>
                                {extraTime && (
                                    <>
                                        <span
                                            className="absolute -translate-x-1/2"
                                            style={{ left: `${(FULLTIME_DURATION / MATCH_DURATION) * 100}%` }}
                                        >
                                            90'
                                        </span>
                                        <span
                                            className="absolute -translate-x-1/2"
                                            style={{ left: `${(ET_HALF / MATCH_DURATION) * 100}%` }}
                                        >
                                            105'
                                        </span>
                                        <span className="absolute right-0">AET</span>
                                    </>
                                )}
                                {!extraTime && (
                                    <span className="absolute right-0">FT</span>
                                )}
                            </div>

                            {/* Timeline bar */}
                            <div
                                className="h-2 rounded-full relative overflow-hidden"
                                style={{ backgroundColor: `${theme.accent}99` }}
                            >
                                {/* Live progress */}
                                {isLive && (
                                    <div
                                        className="absolute top-0 left-0 h-full rounded-full transition-all duration-1000"
                                        style={{ width: `${livePercentage}%`, backgroundColor: theme.accent, opacity: 0.8 }}
                                    />
                                )}

                                {/* Finished progress */}
                                {!isLive && FINAL_STATUSES.includes(game.status) && (
                                    <div
                                        className="absolute top-0 left-0 h-full rounded-full"
                                        style={{ width: '100%', backgroundColor: theme.accent }}
                                    />
                                )}

                                {/* Halftime marker */}
                                <div
                                    className="absolute top-0 bottom-0 w-1"
                                    style={{
                                        left: `${(HALFTIME_DURATION / MATCH_DURATION) * 100}%`,
                                        backgroundColor: league === 'seriea' ? '#ffffff' : theme.border
                                    }}
                                />

                                {/* Extra time markers */}
                                {extraTime && (
                                    <>
                                        <div
                                            className="absolute top-0 bottom-0 w-1"
                                            style={{
                                                left: `${(FULLTIME_DURATION / MATCH_DURATION) * 100}%`,
                                                backgroundColor: league === 'seriea' ? '#ffffff' : theme.border
                                            }}
                                        />
                                        <div
                                            className="absolute top-0 bottom-0 w-1"
                                            style={{
                                                left: `${(ET_HALF / MATCH_DURATION) * 100}%`,
                                                backgroundColor: league === 'seriea' ? '#ffffff' : theme.border
                                            }}
                                        />
                                    </>
                                )}

                                {/* Live position indicator */}
                                {isLive && (
                                    <div
                                        className="absolute w-3 h-3 rounded-full border-2 border-white shadow-lg animate-pulse transition-all duration-1000"
                                        style={{
                                            left: `${livePercentage}%`,
                                            top: '50%',
                                            transform: 'translate(-50%, -50%)',
                                            backgroundColor: theme.accent
                                        }}
                                    />
                                )}

                                {/* Goal markers */}
                                {goalsArray.map((goal, i) => {
                                    const pos = getTimelinePosition(goal.seconds)
                                    const isHome = goal.team_id === game.home_id
                                    return (
                                        <div
                                            key={i}
                                            className="absolute w-3 h-3 rounded-full border-2"
                                            style={{
                                                left: `${pos}%`,
                                                top: '50%',
                                                transform: 'translate(-50%, -50%)',
                                                backgroundColor: isHome ? theme.home : theme.away,
                                                borderColor: theme.secondary,
                                            }}
                                            title={`${cleanName(goal.player_name)} ${goal.minute}`}
                                        />
                                    )
                                })}
                            </div>

                            {/* Live clock label */}
                            {isLive && (
                                <div className="relative h-5 mt-1">
                                    <div
                                        className="absolute text-xs font-medium"
                                        style={{
                                            left: `${livePercentage}%`,
                                            transform: 'translateX(-50%)',
                                            color: theme.accent
                                        }}
                                    >
                                        {secondsDisplay(elapsedSeconds, game?.period)}
                                    </div>
                                </div>
                            )}

                            {/* Goal event list */}
                            <div className="mt-6 space-y-2">
                                {goalsArray
                                    .slice()
                                    .sort((a, b) => (a.seconds || 0) - (b.seconds || 0))
                                    .map((goal, i) => {
                                        const isHome = goal.team_id === game.home_id
                                        return (
                                            <div
                                                key={i}
                                                className={`flex items-center text-sm ${isHome ? 'flex-row' : 'flex-row-reverse'}`}
                                            >
                                                <div className={`flex items-center gap-2 flex-shrink-0 w-16 ${isHome ? 'flex-row' : 'flex-row-reverse'}`}>
                                                    <span
                                                        className="w-3 h-3 rounded-full border-2"
                                                        style={{
                                                            backgroundColor: isHome ? theme.home : theme.away,
                                                            borderColor: theme.secondary
                                                        }}
                                                    />
                                                    <span style={{ color: theme.accent }} className="text-xs">
                                                        {goal.minute}
                                                    </span>
                                                </div>
                                                <div className={`flex items-center gap-2 flex-1 ${isHome ? 'flex-row' : 'flex-row-reverse'}`}>
                                                    <span className="text-white font-medium">
                                                        {cleanName(goal.player_name)}
                                                    </span>
                                                    <span style={{ color: theme.accent, opacity: 0.7 }} className="text-xs">
                                                        {goal.goal_type}
                                                    </span>
                                                </div>
                                            </div>
                                        )
                                    })
                                }
                            </div>
                        </div>
                    </div>

                    {/* Legend */}
                    <div
                        className="flex gap-4 mt-4 text-xs pl-40"
                        style={{ borderTop: `1px solid ${theme.accent}`, paddingTop: '1rem', color: theme.accent }}
                    >
                        <span className="flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: theme.home }} />
                            {game.home_team}
                        </span>
                        <span className="flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: theme.away }} />
                            {game.away_team}
                        </span>
                        <span className="flex items-center gap-1.5">
                            ⚽️ Goal Event (Header/Volley/Other)
                        </span>
                        <span className="flex items-center gap-1.5">
                            🎯 Penalty Goal/Free-kick
                        </span>
                    </div>
                </div>
            )}

            {(!isLive && goalsArray.length === 0) && (
                <div
                    className="border rounded-lg p-6 text-center text-sm"
                    style={{ borderColor: theme.border, backgroundColor: theme.secondary, color: theme.accent }}
                >
                    No goal events recorded for this match.
                </div>
            )}

        </div>
    )
}