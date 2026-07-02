import { useGameWatcher } from '../hooks/useGameWatcher'
import { useNotifications } from '../hooks/useNotifications'
import { useCallback, useEffect, useState, useRef } from 'react'
import { useSubscriptions } from '../hooks/useSubscriptions'

const LIVE_STATUSES = ['STATUS_IN_PROGRESS', 'STATUS_HALFTIME', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF']
const FINAL_STATUSES = ['STATUS_FULL_TIME', 'STATUS_FINAL_PEN', 'STATUS_FINAL_AET', 'STATUS_POSTPONED', 'STATUS_CANCELLED', 'STATUS_ABANDONED']
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

export default function ScoresTab({ onSelectGame, lastUpdate, league, theme }) {
    const [games, setGames] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    const todayRef = useRef(null)
    const hasScrolledToToday = useRef(false)
    
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
            params.append('window', 3) // Fetch games within a week from today
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

    useEffect(() => {
        hasScrolledToToday.current = false
    }, [league]) // Refetch when league changes

    useEffect(() => {
        if (!games?.length || hasScrolledToToday.current) return

        const timer = setTimeout(() => {
            if (todayRef.current) {
                todayRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
            }
            hasScrolledToToday.current = true
        }, 100) // Delay to ensure DOM has rendered
        return () => clearTimeout(timer)
    }, [games])

    useGameWatcher(games, conditionallyEnableNotifications, subscriptions)

    if (loading) return <div className="text-gray-400 p-4">Loading matches...</div>
    if (error)   return <div className="text-red-400 p-4">Error loading matches: {error}</div>
    if (!games?.length) return <div className="text-white p-4">No matches found within a week from today.</div>

    const groupByDate = (games) => {
        const groups = {}

        // Compare dates in Eastern time
        const easternDate = (dateStr) => {
            if (!dateStr) return null
            const normalized = dateStr
                .replace(' ', 'T')
                .replace(/\+00:00$/, 'Z')
                .replace(/\+00$/, 'Z')
            return new Date(normalized).toLocaleDateString('en-US', {
                timeZone: 'America/New_York'
            })
        }

        const todayEastern    = easternDate(new Date().toISOString())
        const tomorrowD       = new Date()
        tomorrowD.setDate(tomorrowD.getDate() + 1)
        const tomorrowEastern = easternDate(tomorrowD.toISOString())
        const yesterdayD      = new Date()
        yesterdayD.setDate(yesterdayD.getDate() - 1)
        const yesterdayEastern = easternDate(yesterdayD.toISOString())
        
        games.forEach(game => {
            const normalized = (game.start_time || '')
                .replace(' ', 'T')
                .replace(/\+00:00$/, 'Z')
                .replace(/\+00$/, 'Z')

            const gameDate    = new Date(normalized)
            const gameDateEDT = gameDate.toLocaleDateString('en-US', {
                timeZone: 'America/New_York'
            })

            const dateKey = gameDateEDT === todayEastern
                ? 'Today'
                : gameDateEDT === tomorrowEastern
                ? 'Tomorrow'
                : gameDateEDT === yesterdayEastern
                ? 'Yesterday'
                : gameDate.toLocaleDateString('en-US', {
                    weekday:  'long',
                    month:    'long',
                    day:      'numeric',
                    timeZone: 'America/New_York',
                })

            if (!groups[dateKey]) groups[dateKey] = []
            groups[dateKey].push(game)
        })

        Object.keys(groups).forEach(key => {
            groups[key].sort((a, b) => {
                const aLive = LIVE_STATUSES.includes(a.status)
                const bLive = LIVE_STATUSES.includes(b.status)
                if (aLive && !bLive) return -1
                if (!aLive && bLive) return 1
                return toUtcDate(a.start_time) - toUtcDate(b.start_time)
            })
        })

        return groups
    }

    const groupedGames = groupByDate(games)
    const sortedDates = Object.keys(groupedGames).sort((a, b) => {
        const dateA = toUtcDate(groupedGames[a][0]?.start_time)
        const dateB = toUtcDate(groupedGames[b][0]?.start_time)
        return dateA - dateB
    })

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

            {sortedDates.map(dateLabel => (
                <div key={dateLabel} ref={dateLabel === 'Today' ? todayRef : null}>
                    {/* Date header */}
                    <div className="flex items-center gap-3 mb-3">
                        <h2
                            className="text-sm font-semibold uppercase tracking-wider"
                            style={{
                                color: dateLabel === 'Today'
                                    ? theme?.accent
                                    : 'rgba(255,255,255,0.6)'
                            }}
                        >
                            {dateLabel}
                        </h2>
                        {dateLabel === 'Today' && (
                            <span
                                className="text-xs px-2 py-0.5 rounded-full font-medium"
                                style={{ backgroundColor: theme?.accent, color: theme?.primary }}
                            >
                                LIVE
                            </span>
                        )}
                    </div>

                    {/* Game cards for this date */}
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {groupedGames[dateLabel].map(game => (
                            <GameCard
                                key={game.game_id}
                                game={game}
                                onSelect={onSelectGame}
                                isSubscribed={isSubscribed(game.game_id)}
                                onToggleSubscription={() => toggle(game.game_id)}
                                notificationsActive={isActive}
                                theme={theme}
                            />
                        ))}
                    </div>
                </div>
            ))}

            {/* Legend */}
            <div className="border-t border-gray-200 pt-6">
                <p className="text-xs font-semibold uppercase tracking-wider text-[#37003c] opacity-60 mb-3">
                    Legend
                </p>
                <div className="flex flex-wrap gap-4 text-xs text-white">
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

function TeamLogo({ teamId, team, size=10, isNational = false }) {
    const [imgSrc, setImgSrc] = useState(
        `https://a.espncdn.com/i/teamlogos/soccer/500/${teamId}.png`
    )

    const attemptedFallback = useRef(false)

    const handleError = () => {
        if (attemptedFallback.current || !isNational) {
            // Second attempt also failed — just hide
            setImgSrc(null)
            return
        }
        attemptedFallback.current = true
        setImgSrc(
            `https://a.espncdn.com/i/teamlogos/countries/500/${team?.toLowerCase().replace(/ /g, '-')}.png`
        )
    }

    if (!imgSrc) return (
        <div className="w-10 h-10 rounded-full bg-white flex items-center justify-center flex-shrink-0" />
    )
        
    return (
        <div className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0">
            <div className="w-12 h-12 rounded-full bg-white flex items-center justify-center flex-shrink-0">
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

function GameCard({ game, onSelect, isSubscribed, onToggleSubscription, notificationsActive, theme }) {
    const isLive = LIVE_STATUSES.includes(game.status)
    const isFinal = FINAL_STATUSES.includes(game.status)

    const startTimeUTC = toUtcDate(game.start_time)

    const formattedTime = startTimeUTC?.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        timeZone: 'America/New_York'
    }) ?? '—'

    const badgeText = (isFinal, isLive, game) => {
        if (isLive && game.status === 'STATUS_HALFTIME') return 'HT'
        if (isLive) return `🔴 ${game.clock || 'Live'}`
        if (isFinal) {
            if (['STATUS_POSTPONED', 'STATUS_CANCELLED', 'STATUS_ABANDONED'].includes(game.status)) {
                return game.status.replace('STATUS_', '').replace('_', ' ')
            } else {
                return 'FT'
            }
        }

        if (formattedTime) return 'KO'

        return 'TBD'
    }

    return (
        <div
            onClick={() => onSelect(game.game_id)}
            style={{ backgroundColor: theme.secondary, borderColor: theme.border }}
            className="rounded-lg p-4 cursor-pointer transition-colors relative"
            title='Click to view match details'
            onMouseEnter={e => e.currentTarget.style.borderColor = theme.accent}
            onMouseLeave={e => e.currentTarget.style.borderColor = theme.border}
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
                    {startTimeUTC?.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
                </span>
            </div>

            {/* Score row */}
            <div className="flex items-center justify-between">

                {/* Home team */}
                <div className="flex-1 flex flex-col items-center gap-1 pr-4">
                    <TeamLogo teamId={game.home_id} team={game.home_team} isNational={game.league === 'worldcup'} />
                    <span className="text-lg font-medium text-white">{game.home_team}</span>
                </div>

                {/* Score */}
                <div className="mx-4 flex items-center gap-3">
                    {isFinal || isLive ? (
                        <>
                            <span className="text-3xl font-bold text-white">{game.shootout_home ? `(${game.shootout_home})` : ``} {game.home_score}</span>
                            <span className="text-purple-600">–</span>
                            <span className="text-3xl font-bold text-white">{game.away_score} {game.shootout_away ? `(${game.shootout_away})` : ``} </span>
                        </>
                    ) : (
                        <span className="text-purple-300 text-lg">vs</span>
                    )}
                </div>
                
                {/* Away team */}
                <div className="flex-1 flex flex-col items-center gap-1 pl-4">
                    <TeamLogo teamId={game.away_id} team={game.away_team} isNational={game.league === 'worldcup'} />
                    <span className="text-lg font-medium text-white">{game.away_team}</span>
                </div>
            </div>

            {/* Period indicator for live games */}
            {isLive && (
                <div className="mt-2 text-center text-xs text-purple-300">
                    {game.status === 'STATUS_FIRST_HALF' ? '1st Half' : 
                        game.status === 'STATUS_SECOND_HALF' ? '2nd Half' : 'Halftime'}
                </div>
            )}

            {!isLive && !isFinal && (
                <div className="mt-2 text-center text-sm text-purple-300">
                    Kickoff @ {formattedTime} EDT
                </div>
            )}

            {isFinal && (
                <div className="mt-2 text-center text-sm text-purple-300">
                    {game.status.replace('STATUS_', '').replace('_', ' ')}
                </div>
            )}
        </div>
    )
}