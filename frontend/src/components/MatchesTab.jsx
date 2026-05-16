import { useEffect, useRef, useState } from "react";
import { usePoll } from "../hooks/usePoll";

const LIVE_STATUSES = ['STATUS_IN_PROGRESS', 'STATUS_HALFTIME', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF']
const FINAL_STATUSES = ['STATUS_FULL_TIME', 'STATUS_FINAL']

const MATCH_DURATION = 5700; // 95 minutes in seconds

const getTimelinePosition = (currentSeconds) => {
  const percentage = (currentSeconds / MATCH_DURATION) * 100;
  return Math.min(percentage, 98);
}

const parseClock = (clockStr, period) => {
    if (!clockStr) return period === 1 ? 0 : 2700; // Start of match or start of second half
    const parts = clockStr.replace(/'/g, '').split('+');
    const base = parseInt(parts[0]) || 0
    const extra = parseInt(parts[1]) || 0
    return (base + extra) * 60
}

const getPercentage = (game) => {
    if (!game) return null
    if (!LIVE_STATUSES.includes(game.status)) return null
    if (game.status === 'STATUS_HALFTIME') return (2700 / MATCH_DURATION) * 100

    const elapsed = parseClock(game.clock, game.period)

    const total = game.period === 2 ? 2700 + elapsed : elapsed
    return Math.min((total / MATCH_DURATION) * 100, 98)
}

const secondsDisplay = (seconds) => {
    const mins = Math.floor(seconds / 60)
    if (mins > 90) return `90'+${mins - 90}'`
    if (mins >= 45 && seconds < 2700) return `45'+${mins - 45}'`
    return `${mins}'`
}

const GOAL_ICON = {
    'Goal': '⚽',
    'Goal - Volley': '⚽',
    'Penalty - Scored': '🎯',
    'Goal - Header': '⚽'
}

export default function MatchesTab({ gameId, onBack }) {
    const { data: game, loading: gameLoading, error: gameError } = usePoll(`/games/${gameId}`, 15000)
    const isUpcoming = game != null && !LIVE_STATUSES.includes(game.status) && !FINAL_STATUSES.includes(game.status)

    const { data: goals, loading: goalsLoading, error: goalsError } = usePoll(
        game != null &&!isUpcoming ? `/games/${gameId}/stats` : null,
        30000
    )

    const loading = gameLoading || goalsLoading
    const error = gameError || goalsError
    const goalsArray = Array.isArray(goals) ? goals : []

    const [elapsedSeconds, setElapsedSeconds] = useState(0)
    const [barSeconds, setBarSeconds] = useState(0)
    const lastSynched = useRef(null)

    useEffect(() => {
      if(!game?.clock || !LIVE_STATUSES.includes(game?.status ?? '')) return;

      if (game.clock) {
        const parsed = parseClock(game.clock, game.period)
        const total = game.period === 2 ? 2700 + parsed : parsed

        setElapsedSeconds(total)
        setBarSeconds(total)
        lastSynched.current = Date.now()
      }
      
      const timer = setInterval(() => {
        setElapsedSeconds(prev => Math.min(prev + 1, MATCH_DURATION))
      }, 1000)

      return () => clearInterval(timer)
    }, [game])

    if (!gameId) return <div className="text-[#37003c] p-4">Please select a game from the Scores tab to view details.</div>;
    if (loading) return <div className="text-[#37003c] p-4">Loading game details...</div>;
    if (error) return <div className="text-[#37003c] p-4">Error: {gameError || goalsError}</div>;
    if (!game) return <div className="text-[#37003c] p-4">Game not found.</div>;

    const progressPercent = getPercentage(game)
    const isLive = game && LIVE_STATUSES.includes(game.status)
    const livePercentage = isLive 
        ? Math.min((barSeconds / MATCH_DURATION) * 100, 98) 
        : progressPercent

    const homeGoals = goalsArray.filter(g => g.team_id === game.home_id);
    const awayGoals = goalsArray.filter(g => g.team_id === game.away_id);

    return (
        <div className="max-w-4xl mx-auto space-y-6">

            {/* Back button */}
            <button
                onClick={onBack}
                className="flex items-center gap-2 text-sm text-[#37003c] hover:text-[#00ff85] hover:bg-purple-700 bg-[#00ff85] rounded-lg p-2 transition-colors"
            >
                ← Back to Scores
            </button>

            {/* Match header card */}
            <div className="bg-[#2d0032] border border-purple-800 rounded-lg p-6">

                {/* Status */}
                <div className="text-center text-xs text-purple-400 mb-4 uppercase tracking-wider">
                    {game.status_detail}
                </div>

                {/* Score row */}
                <div className="grid grid-cols-3 items-center gap-4">

                  {/* Home team */}
                    <div className="flex flex-col items-end">
                        <div className="flex items-center gap-3">
                            <div className="text-2xl font-bold text-white text-center">
                                {game.home_team_name || game.home_team}
                            </div>
                            <img
                                src={`https://a.espncdn.com/i/teamlogos/soccer/500/${game.home_id}.png`}
                                alt={game.home_team_name || game.home_team}
                                className="w-16 h-16 object-contain"
                                onError={(e) => {e.target.style.display = 'none'}}
                            />
                        </div>
                    </div>

                    {/* Score */}
                    <div className="text-center">
                        <div className="text-5xl font-bold text-white tracking-tight">
                            {game.home_score} – {game.away_score}
                        </div>
                    </div>

                    {/* Away team */}
                    <div className="flex flex-col items-start">
                        <div className="flex items-center gap-3">
                            <img
                                src={`https://a.espncdn.com/i/teamlogos/soccer/500/${game.away_id}.png`}
                                alt={game.away_team_name || game.away_team}
                                className="w-16 h-16 object-contain"
                                onError={(e) => {e.target.style.display = 'none'}}
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
                                <div key={i} className="text-xs text-purple-300">
                                    {GOAL_ICON[g.goal_type] || ' ⚽ '} {g.player_name} {g.own_goal && ' (OG) '} {g.penalty_goal && ' (P) '} {g.minute}
                                </div>
                            ))}
                        </div>

                        <div />

                        <div className="space-y-1">
                            {awayGoals.map((g, i) => (
                                <div key={i} className="text-xs text-purple-300">
                                    {GOAL_ICON[g.goal_type] || ' ⚽ '} {g.player_name} {g.own_goal && ' (OG) '} {g.penalty_goal && ' (P) '} {g.minute}
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* Goal timeline */}
            {(isLive || goalsArray.length > 0) && (
                <div className="bg-[#2d0032] border border-purple-800 rounded-lg p-6">
                    <h3 className="text-sm font-semibold text-white mb-6 uppercase tracking-wider">
                        Goal Timeline
                    </h3>

                    <div className="flex gap-6">
                        <div className="flex-1">

                            {/* Minute labels below bar */}
                            <div className="relative text-xs text-purple-500 mb-2 h-4">
                                <span className="absolute left-0">0'</span>
                                <span 
                                    className="absolute -translate-x-1/2"
                                    style={{ left: `${(2700/5700) * 100}%`}}
                                 > HT 
                                 </span>
                                <span className="absolute right-0">FT</span>
                            </div>

                            
                            {/* Timeline bar */}
                            <div className="h-2 bg-purple-900 rounded-full relative overflow-hidden">
                                
                                {/* Live progress indicator */}
                                {isLive && progressPercent !== null && (
                                    <div 
                                        className="absolute top-0 left-0 h-full bg-[#00ff85] opacity-80 rounded-full transition-all duration-1000"
                                        style={{ width: `${livePercentage}%` }}
                                    />
                                )}

                                {!isLive && FINAL_STATUSES.includes(game.status) && (
                                    <div 
                                        className="absolute top-0 left-0 h-full bg-[#00ff85] rounded-full transition-all duration-1000"
                                        style={{ width: `100%` }}
                                    />
                                )}

                                {/* Halftime marker */}
                                <div
                                    className="absolute top-0 bottom-0 w-1 bg-purple-500"
                                    style={{ left: `${(2700 / 5700) * 100}%` }}
                                />

                                {/* Position inidicator */}
                                {isLive && progressPercent !== null && (
                                    <div
                                        className="absolute w-3 h-3 bg-[#00ff85] rounded-full border-2 border-white shadow-lg animate-pulse transition-all duration-1000"
                                        style={{ left: `${livePercentage}%`, top: '50%', transform: 'translate(-50%, -50%)' }}
                                    />
                                )}
                
                                {/* Goal markers on the bar */}
                                {goalsArray.map((goal, i) => {
                                    const pos = getTimelinePosition(goal.seconds)
                                    const isHome = goal.team_id === game.home_id
                                    return (
                                        <div
                                            key={i}
                                            className={`absolute w-3 h-3 rounded-full border-2 border-[#2d0032] ${
                                                isHome ? 'bg-red-500' : 'bg-blue-500'
                                            }`}
                                            style={{ left: `${pos}%`, top: '50%', transform: 'translate(-50%, -50%)' }}
                                            title={`${goal.player_name} ${goal.minute}`}
                                        />
                                    )
                                })}
                            </div>

                            {/* Live clock */}
                            {isLive && progressPercent !== null && (
                                <div className="relative h-5 mt-1">
                                    <div
                                        className="absolute text-xs text-[#00ff85] font-medium"
                                        style={{ left: `${livePercentage}%`, transform: 'translateX(-50%)' }}
                                    > {secondsDisplay(elapsedSeconds)} 
                                    </div>
                                </div>
                            )}

                            {/* Goal event list below timeline */}
                            <div className="mt-6 space-y-2">
                                {goalsArray
                                    .slice()
                                    .sort((a, b) => (a.seconds || 0) - (b.seconds || 0))
                                    .map((goal, i) => {
                                        const isHome = goal.team_id === game.home_id
                                        return (
                                            <div key={i} className={`flex items-center text-sm ${
                                                isHome ? 'flex-row' : 'flex-row-reverse'
                                            }`}>
                                                <div className={`flex items-center gap-2 flex-shrink-0 w-16 ${
                                                    isHome ? 'flex-row' : 'flex-row-reverse'
                                                }`}>
                                                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                                                        isHome ? 'bg-red-500' : 'bg-blue-500'
                                                    }`} />
                                                    <span className="text-purple-300 text-xs"> {goal.minute} </span>
                                                </div>
                                                
                                                <div className={`flex items-center gap-2 flex-1 ${isHome ? 'flex-row' : 'flex-row-reverse'}`}>
                                                    <span className="text-white font-medium">{goal.player_name}</span>
                                                    <span className="text-purple-300 text-xs"> {goal.goal_type} </span>
                                                </div>
                                            </div>
                                        )
                                    })
                                }
                            </div>
                        </div>
                    </div>

                    {/* Legend */}
                    <div className="flex gap-4 mt-4 text-xs text-purple-300">
                        <span className="flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-red-500" />
                            {game.home_team}
                        </span>
                        <span className="flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-blue-500" />
                            {game.away_team}
                        </span>
                        <span className="flex items-center gap-1.5">
                            ⚽️ Goal Event (Header/Volley/Other)
                        </span>
                        <span className="flex items-center gap-1.5">
                            🎯 Penalty Goal
                        </span>
                    </div>
                </div>
            )}

            {(!isLive && goalsArray.length === 0) && (
                <div className="bg-[#2d0032] border border-purple-800 rounded-lg p-6 text-center text-purple-300 text-sm">
                    No goal events recorded for this match.
                </div>
            )}

        </div>
    )
}