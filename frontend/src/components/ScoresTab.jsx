import { useGameWatcher } from '../hooks/useGameWatcher'
import { useNotifications } from '../hooks/useNotifications'
import { use, useCallback, useEffect, useState } from 'react'
import { useSubscriptions } from '../hooks/useSubscriptions'

const LIVE_STATUSES = ['STATUS_IN_PROGRESS', 'STATUS_HALFTIME', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF']
const FINAL_STATUSES = ['STATUS_FULL_TIME', 'STATUS_FINAL']

export default function ScoresTab({ onSelectGame, lastUpdate, league }) {
    const [games, setGames] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    
    const [notificationsEnabled, setNotificationsEnabled] = useState(Notification.permission === 'granted')
    const { notify } = useNotifications()
    const { subscriptions, toggle, isSubscribed } = useSubscriptions()

    const isBlocked = Notification.permission === 'denied'
    const isActive = notificationsEnabled && !isBlocked

    const conditionallyEnableNotifications = (...args) => { if (isActive) notify(...args) }

    const fetchGames = useCallback(async () => {
        try {
            const params = new URLSearchParams()
            if (league) params.append('league', league)
            const res = await fetch(`${process.env.REACT_APP_API_URL || 'http://localhost:8000'}/games?${params}`)
            const data = await res.json()
            setGames(data)
            setLoading(false)
        } catch (err) {
            setError(err.message || 'Failed to load matches')
            setLoading(false)
        }
    }, [league])

    useEffect(() => {
        fetchGames()
    }, [fetchGames])

    useEffect(() => {
        if (lastUpdate?.type === 'games' || lastUpdate?.type === 'goals') {
            fetchGames()
        }
    }, [lastUpdate, fetchGames])

    useEffect(() => {
        const interval = setInterval(fetchGames, 60 * 1000) // Poll every 60 seconds
        return () => clearInterval(interval)
    }, [fetchGames])

    useGameWatcher(games, conditionallyEnableNotifications, subscriptions)

    if (loading) return <div className="text-gray-400 p-4">Loading matches...</div>
    if (error)   return <div className="text-red-400 p-4">Error loading matches: {error}</div>
    if (!games?.length) return <div className="text-[#37003c] p-4">No matches found today.</div>

    const live = games.filter(g => LIVE_STATUSES.includes(g.status))
    const completed = games.filter(g => FINAL_STATUSES.includes(g.status))
    const upcoming  = games.filter(g => !LIVE_STATUSES.includes(g.status) && !FINAL_STATUSES.includes(g.status))

    return (
        <div className="space-y-8">

            {/* Notification toggle */}
            <div className='flex justify-end'>
                <button
                    onClick={() => {
                        if (isBlocked) return
                        setNotificationsEnabled(prev => !prev)
                    }}

                    className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${
                        isBlocked ? 'bg-gray-800 text-gray-500 cursor-not-allowed' :
                        isActive ? 'bg-[#00ff85] text-[#37003c] hover:bg-[#00e676]' : 'bg-purple-900 text-purple-300'
                    }`}
                    title={isBlocked ? 'Notifications are blocked. Please enable them in your browser settings.' : ''}
                >
                    {isBlocked
                        ? '🚫 Notifications Blocked'
                        : isActive
                            ? '🔔 Notifications On'
                            : '🔕 Notifications Off'
                    }                
                </button>
            </div>

            <Section title="Live" accent="green" games={live} onSelect={onSelectGame} isSubscribed={isSubscribed} onToggleSubscription={toggle} notificationsActive={isActive} />
            <Section title="Completed" accent="gray" games={completed} onSelect={onSelectGame} isSubscribed={isSubscribed} onToggleSubscription={toggle} notificationsActive={isActive} />
            <Section title="Upcoming" accent="blue" games={upcoming} onSelect={onSelectGame} isSubscribed={isSubscribed} onToggleSubscription={toggle} notificationsActive={isActive} />

            {/* Legend */}
            <div className="border-t border-gray-200 pt-6">
                <p className="text-xs font-semibold uppercase tracking-wider text-[#37003c] opacity-60 mb-3">
                    Legend
                </p>
                <div className="flex flex-wrap gap-4 text-xs text-[#37003c]">
                    <span className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded bg-[#00ff85] text-[#37003c] font-semibold">
                            🔴
                        </span>
                        Match in progress
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded bg-white opacity-70 text-[#37003c] font-semibold border border-gray-200">
                            FT
                        </span>
                        Full-time
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded bg-purple-300 text-[#37003c] font-semibold">
                            HT
                        </span>
                        Halftime
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded bg-purple-300 text-[#37003c] font-semibold">
                            KO
                        </span>
                        Upcoming Kickoff
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="w-3 h-3 rounded-full bg-[#00ff85] inline-block" />
                        Click any card to view match details
                    </span>
                </div>
            </div>
        </div>
    )
}

function Section({ title, accent, games, onSelect, isSubscribed, onToggleSubscription, notificationsActive }) {
    if (!games.length) return null

    const colors = {
        green: 'text-[#37003c] font-bold',
        gray:  'text-[#37003c] font-bold',
        blue:  'text-[#37003c] font-bold'
    }

    return (
        <div>
            <h2 className={`text-sm font-semibold uppercase tracking-wider mb-3 ${colors[accent]}`}>
                {title} — {games.length} match{games.length !== 1 ? 'es' : ''}
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {games.map(game => (
                    <GameCard key={game.game_id} game={game} onSelect={onSelect} isSubscribed={isSubscribed(game.game_id)} onToggleSubscription={() => {onToggleSubscription(game.game_id)}} notificationsActive={notificationsActive} />
                ))}
            </div>
        </div>
    )
}

function GameCard({ game, onSelect, isSubscribed, onToggleSubscription, notificationsActive }) {
    const isLive = LIVE_STATUSES.includes(game.status)
    const isFinal = FINAL_STATUSES.includes(game.status)

    const startTimeUTC = game.start_time ? new Date(game.start_time + 'Z') : null

    const formattedTime = startTimeUTC?.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        timeZone: 'America/New_York'
    }) ?? '—'

    const badgeText = (isFinal, isLive, game) => {
        if (isLive && game.status === 'STATUS_HALFTIME') return 'HT'
        if (isLive) return `🔴 ${game.clock || 'Live'}`
        if (isFinal) return 'FT'

        if (formattedTime) return 'KO'

        return 'TBD'
    }

    function TeamLogo({ teamId, team, size=10 }) {
        return (
            <div className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0">
                <img
                    src={`https://a.espncdn.com/i/teamlogos/soccer/500/${teamId}.png`}
                    alt={team}
                    className={`w-${size} h-${size} object-contain`}
                    onError={(e) => {e.target.style.display = 'none'}}
                />
            </div>
        )
    }

    return (
        <div
            onClick={() => onSelect(game.game_id)}
            className="bg-[#2d0032] border border-purple-800 rounded-lg p-4 cursor-pointer hover:border-[#00ff85] transition-colors relative"
            title='Click to view match details'
        >
            {/* Subscription toggle */}
            {notificationsActive && (
                <button
                    onClick={(e) => {
                        e.stopPropagation()
                        onToggleSubscription()
                    }}
                    className={`absolute top-4 right-4 text-md transition-colors rounded ${
                        isSubscribed ? 'bg-[#00ff85]' : 'bg-purple-600 hover:bg-purple-300'}`}
                    title={isSubscribed ? 'Unsubscribe' : 'Subscribe to notifications'}
                >
                    {!isFinal ?
                        isSubscribed ? '🔔' : '🔕'
                        : ''
                    }
                </button>
            )}

            {/* Status bar */}
            <div className="flex items-center justify-between">
                <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
                    isLive && game.status === 'STATUS_HALFTIME' ? 'bg-purple-300 text-[#37003c]' :
                    isLive ? 'bg-[#00ff85] text-[#37003c]' :
                    isFinal ? 'bg-white opacity-70 text-[#37003c] border border-gray-200' :
                            'bg-purple-300 text-[#37003c]'
                }`}>
                    {badgeText(isFinal, isLive, game)}
                </span>
            </div>

            <div className='text-center text-xs text-purple-300 mb-4'>
                <span className="text-sm text-purple-300">
                    {new Date(startTimeUTC).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
                </span>
            </div>

            {/* Score row */}
            <div className="flex items-center justify-between">

                {/* Home team */}
                <div className="flex-1 flex flex-col items-center gap-1 pr-4">
                    <TeamLogo teamId={game.home_id} team={game.home_team} />
                    <span className="text-lg font-medium text-white">{game.home_team}</span>
                </div>

                {/* Score */}
                <div className="mx-4 flex items-center gap-2">
                    {isFinal || isLive ? (
                        <>
                            <span className="text-3xl font-bold text-white">{game.home_score}</span>
                            <span className="text-purple-600">–</span>
                            <span className="text-3xl font-bold text-white">{game.away_score}</span>
                        </>
                    ) : (
                        <span className="text-purple-300 text-lg">vs</span>
                    )}
                </div>
                
                {/* Away team */}
                <div className="flex-1 flex flex-col items-center gap-1 pl-4">
                    <TeamLogo teamId={game.away_id} team={game.away_team} />
                    <span className="text-lg font-medium text-white">{game.away_team}</span>
                </div>
            </div>

            {/* Period indicator for live games */}
            {isLive && (
                <div className="mt-2 text-center text-xs text-purple-300">
                    {Number(game.period) === 1 ? '1st Half' : '2nd Half'}
                </div>
            )}

            {!isLive && !isFinal && (
                <div className="mt-2 text-center text-sm text-purple-300">
                    Kickoff @ {formattedTime} EDT
                </div>
            )}

            {isFinal && (
                <div className="mt-2 text-center text-sm text-purple-300">
                    Full-time
                </div>
            )}
        </div>
    )
}