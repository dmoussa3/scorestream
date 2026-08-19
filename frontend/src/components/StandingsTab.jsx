import { useCallback, useEffect, useState, useRef } from "react";

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000'

const rowColors = (position, theme, league) => {
    if (league === 'mls') {
        if (position <= 9) return { 
            borderBottom: '1px solid #81D6AC',
            backgroundColor: 'rgba(23, 37, 84, 0.4)',
            borderLeft: '4px solid #81D6AC' 
        }
        return { borderBottom: `1px solid ${theme?.border}` }
    }
    if (position <= 4) return {
        borderBottom: '1px solid #3b82f6',
        backgroundColor: 'rgba(23, 37, 84, 0.4)',
        borderLeft: '4px solid #3b82f6'
    }
    if (position === 5) return {
        borderBottom: '1px solid #f97316',
        backgroundColor: 'rgba(23, 37, 84, 0.4)',
        borderLeft: '4px solid #f97316'
    }
    if ((league === 'ligue1' || league === 'bundesliga' || league === 'seriea') && position === 5) return {
        borderBottom: '1px solid #f97316',
        backgroundColor: 'rgba(67, 20, 7, 0.4)',
        borderLeft: '4px solid #f97316'
    }
    if (position === 6) return {
        borderBottom: '1px solid #22c55e',
        backgroundColor: 'rgba(5, 46, 22, 0.4)',
        borderLeft: '4px solid #22c55e'
    }
    if (league === 'ligue1' || league === 'bundesliga') {
        if (position === 16) return {
            borderTop: '2px solid #ef4444',
            borderBottom: '1px solid #f87171',
            backgroundColor: 'rgba(254, 202, 202, 0.4)',
            borderLeft: '4px solid #ef4444'
        }
        if (position >= 16) return {
            borderBottom: '1px solid #f87171',
            backgroundColor: 'rgba(254, 202, 202, 0.4)',
            borderLeft: '4px solid #ef4444'
        }
    }
    if (position === 18) return {
        borderTop: '2px solid #ef4444',
        borderBottom: '1px solid #f87171',
        borderLeft: '4px solid #ef4444',
        backgroundColor: 'rgba(69, 10, 10, 0.4)'
    }
    if (position >= 18) return {
        borderBottom: '1px solid #f87171',
        backgroundColor: 'rgba(69, 10, 10, 0.4)',
        borderLeft: '4px solid #ef4444'
    }
    return { borderBottom: `1px solid ${theme?.border}` }
}

// Defined outside component so it doesn't remount on every render
function TeamLogo({ teamId, teamName, logoUrl, size = 7}) {
    const [imgSrc, setImgSrc] = useState(
        logoUrl || `https://a.espncdn.com/i/teamlogos/soccer/500/${teamId}.png`
    )
    const attemptedFallback = useRef(false)

    const handleError = () => {
        if (attemptedFallback.current) {
            setImgSrc(null)
            return
        }
        attemptedFallback.current = true
        setImgSrc(
            `https://a.espncdn.com/i/teamlogos/countries/500/${teamName?.toLowerCase().replace(/ /g, '-')}.png`
        )
    }

    if (!imgSrc) return (
        <div className="w-9 h-9 rounded-full bg-white flex-shrink-0" />
    )

    return (
        <div className="w-9 h-9 rounded-full bg-white flex items-center justify-center flex-shrink-0">
            <img
                src={imgSrc}
                alt={teamName}
                className={`w-${size} h-${size} object-contain`}
                onError={handleError}
            />
        </div>
    )
}

function StandingsTable({ teams, theme, league }) {
    return (
        <table className="w-full text-sm">
            <thead>
                <tr
                    style={{ color: theme?.text, borderColor: theme?.border }}
                    className="border-b text-xs font-semibold uppercase tracking-wider"
                >
                    <th className="px-4 py-3 text-center w-8">#</th>
                    <th className="px-4 py-3 text-left">Team</th>
                    <th className="px-2 py-3 text-center">MP</th>
                    <th className="px-2 py-3 text-center">W</th>
                    <th className="px-2 py-3 text-center">D</th>
                    <th className="px-2 py-3 text-center">L</th>
                    <th className="px-2 py-3 text-center">GD</th>
                    <th className="px-2 py-3 text-center">GF</th>
                    <th className="px-2 py-3 text-center">GA</th>
                    <th className="px-2 py-3 text-center font-bold">Pts</th>
                </tr>
            </thead>
            <tbody>
                {teams.map((team, index) => {
                    const position = index + 1
                    const rowStyle = rowColors(position, theme, league)
                    return (
                        <tr
                            key={team.team_id || team.team_name}
                            style={rowStyle}
                            className="hover:opacity-80 transition-colors duration-300"
                        >
                            <td className="px-4 py-3 text-center text-white font-medium">
                                {position}
                            </td>
                            <td className="px-4 py-3">
                                <div className="flex items-center gap-3">
                                    <TeamLogo
                                        teamId={team.team_id}
                                        teamName={team.team_name}
                                        logoUrl={team.logo_url}
                                    />
                                    <div className="flex flex-col">
                                        <span
                                            style={{ color: theme?.text }}
                                            className="font-medium whitespace-nowrap"
                                        >
                                            {team.team_name}
                                        </span>
                                            <span
                                                className="text-xs opacity-80"
                                                style={{ color: team.note_color || '#ffffff' }}
                                            >
                                                {team.note}
                                            </span>
                                    </div>
                                </div>
                            </td>
                            <td className="px-2 py-3 text-center" style={{ color: theme?.text }}>
                                {team.matches_played}
                            </td>
                            <td className="px-2 py-3 text-center" style={{ color: theme?.text }}>
                                {team.wins}
                            </td>
                            <td className="px-2 py-3 text-center" style={{ color: theme?.text }}>
                                {team.draws}
                            </td>
                            <td className="px-2 py-3 text-center" style={{ color: theme?.text }}>
                                {team.losses}
                            </td>
                            <td className={`px-2 py-3 text-center ${
                                team.goal_diff > 0 ? 'text-[#00ff85]' :
                                team.goal_diff < 0 ? 'text-red-300' :
                                'text-purple-200'
                            }`}>
                                {team.goal_diff > 0 ? `+${team.goal_diff}` : team.goal_diff}
                            </td>
                            <td className="px-2 py-3 text-center text-white">
                                {team.goals_for}
                            </td>
                            <td className="px-2 py-3 text-center text-white">
                                {team.goals_against}
                            </td>
                            <td
                                className="px-2 py-3 text-center font-bold"
                                style={{ color: theme?.text }}
                            >
                                {team.points}
                            </td>
                        </tr>
                    )
                })}
            </tbody>
        </table>
    )
}

export default function StandingsTab({ lastUpdate, league = 'epl', theme }) {
    const [standings, setStandings] = useState(null)
    const [loading, setLoading]     = useState(true)
    const [error, setError]         = useState(null)

    const isEurope = ['epl', 'laliga', 'bundesliga', 'seriea', 'ligue1'].includes(league)
    const isMls = league === 'mls'

    const fetchStandings = useCallback(async () => {
        try {
            const response = await fetch(`${API}/standings?league=${league}`)
            const data     = await response.json()
            setStandings(data)
            setLoading(false)
        } catch (err) {
            setError(err.message)
            setLoading(false)
        }
    }, [league])

    useEffect(() => { fetchStandings() }, [fetchStandings])

    useEffect(() => {
        if (lastUpdate?.type === 'standings') fetchStandings()
    }, [lastUpdate, fetchStandings])

    useEffect(() => {
        const interval = setInterval(fetchStandings, 60 * 1000)
        return () => clearInterval(interval)
    }, [fetchStandings])

    if (loading) return <div className="p-4" style={{ color: theme?.accent }}>Loading standings...</div>
    if (error)   return <div className="p-4 text-red-400">Error: {error}</div>
    if (!standings?.length) return <div className="p-4" style={{ color: theme?.accent }}>No standings data available.</div>

    const easternConference = isMls
        ? [...standings]
            .filter(t => t.group_name === 'Eastern Conference')
            .sort((a, b) => a.rank - b.rank)
        : []

    const westernConference = isMls
        ? [...standings]
            .filter(t => t.group_name === 'Western Conference')
            .sort((a, b) => a.rank - b.rank)
        : []

    return (
        <div className="max-w-6xl mx-auto">

            {/* MLS — two conference tables stacked */}
            {isMls ? (
                <div className="flex flex-col gap-8">
                    {[
                        { label: 'Eastern Conference', teams: easternConference },
                        { label: 'Western Conference', teams: westernConference },
                    ].map(({ label, teams }) => (
                        <div key={label}>
                            {/* Conference header */}
                            <div className="flex items-center gap-3 mb-3">
                                <h3
                                    className="text-sm font-bold uppercase tracking-widest"
                                    style={{ color: theme?.accent }}
                                >
                                    {label}
                                </h3>
                                <div
                                    className="flex-1 h-px opacity-20"
                                    style={{ backgroundColor: theme?.accent }}
                                />
                            </div>

                            {/* Table */}
                            <div className="flex gap-6 items-start">
                                <div
                                    style={{ backgroundColor: theme?.secondary, borderColor: theme?.border }}
                                    className="flex-1 rounded-lg border overflow-hidden"
                                >
                                    <StandingsTable teams={teams} theme={theme} league={league} />
                                </div>

                                {/* MLS legend */}
                                <div className="flex-shrink-0 flex flex-col gap-3 pt-2 text-xs text-white ml-4">
                                    <span className="font-semibold uppercase tracking-wider text-white mb-1">
                                        Zones
                                    </span>
                                    <div className="flex items-center gap-2">
                                        <span className="w-8 h-1 inline-block rounded-full" style={{ backgroundColor: '#81D6AC' }} />
                                        <span className="text-xs" style={{ color: theme?.text }}>
                                            MLS Cup Playoffs (1-9)
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>

            ) : (
                /* European club leagues — single table + legend */
                <div className="flex gap-6 items-start">
                    <div
                        style={{ backgroundColor: theme?.secondary, borderColor: theme?.border }}
                        className="flex-1 rounded-lg border overflow-hidden"
                    >
                        <StandingsTable teams={standings} theme={theme} league={league} />
                    </div>

                    {/* Europe legend */}
                    <div className="flex-shrink-0 flex flex-col gap-3 pt-2 text-xs text-white ml-4">
                        <span className="font-semibold uppercase tracking-wider text-white mb-1">
                            Zones
                        </span>
                        {isEurope && (
                            <div className="flex items-center gap-2">
                                <span className="w-8 h-1 bg-blue-500 inline-block rounded-full" />
                                <span className="text-xs opacity-60" style={{ color: theme?.text }}>
                                    UEFA Champions League (1-4)
                                </span>
                            </div>
                        )}
                        {isEurope && (
                            <div className="flex items-center gap-2">
                                <span className="w-8 h-1 bg-orange-500 inline-block rounded-full" />
                                <span className="text-xs opacity-60" style={{ color: theme?.text }}>
                                    UEFA Europa League (5)
                                </span>
                            </div>
                        )}
                        {isEurope && (
                            <div className="flex items-center gap-2">
                                <span className="w-8 h-1 bg-green-500 inline-block rounded-full" />
                                <span className="text-xs opacity-60" style={{ color: theme?.text }}>
                                    UEFA Conference League (6)
                                </span>
                            </div>
                        )}
                        {isEurope && (
                            <div className="flex items-center gap-2">
                                <span className="w-8 h-1 bg-red-500 inline-block rounded-full" />
                                <span className="text-xs opacity-60" style={{ color: theme?.text }}>
                                    {league === 'epl' || league === 'laliga' || league === 'seriea'
                                        ? 'Relegation (18-20)'
                                        : league === 'bundesliga' || league === 'ligue1'
                                        ? 'Relegation (16-18)'
                                        : ''}
                                </span>
                            </div>
                        )}
                    </div>
                </div>
            )}

            <div className="mt-3 text-xs text-white text-right opacity-60">
                Updates every 5 minutes
            </div>
        </div>
    )
}