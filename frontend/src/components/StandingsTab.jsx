import { useWebSocket } from "../hooks/useWebSocket";
import { useCallback, useEffect, useState } from "react";

const rowColors = (position, theme, league) => {
    if (position <= 4) return {
        borderBottom: '1px solid #3b82f6',          // blue-500
        backgroundColor: 'rgba(23, 37, 84, 0.4)',
        borderLeft: '4px solid #3b82f6'             // blue-500
    }
    if ((league === 'epl' || league === 'laliga') && position === 5) return {
        borderBottom: '1px solid #3b82f6',          // blue-500
        backgroundColor: 'rgba(23, 37, 84, 0.4)',
        borderLeft: '4px solid #3b82f6'             // blue-500
    }
    if ((league === 'ligue1' || league === 'bundesliga' || league === 'seriea') && position === 5) return {
        borderBottom: '1px solid #f97316',           // orange-500
        backgroundColor: 'rgba(67, 20, 7, 0.4)',
        borderLeft: '4px solid #f97316'             // orange-500
    }
    if (position === 6 && (league === 'ligue1')) return {
        borderBottom: '1px solid #22c55e',           // green-500
        backgroundColor: 'rgba(5, 46, 22, 0.4)',    // green-950 at 40% opacity
        borderLeft: '4px solid #22c55e'              // green-500
    }
    if (position === 6 && (league === 'bundesliga' || league === 'seriea' || league === 'laliga' || league === 'epl')) return {
         borderBottom: '1px solid #f97316',           // orange-500
        backgroundColor: 'rgba(67, 20, 7, 0.4)',
        borderLeft: '4px solid #f97316'             // orange-500
    }
    if (position === 7 && (league === 'laliga' || league === 'seriea' || league === 'bundesliga')) return {
        borderBottom: '1px solid #22c55e',           // green-500
        backgroundColor: 'rgba(5, 46, 22, 0.4)',    // green-950 at 40% opacity
        borderLeft: '4px solid #22c55e'              // green-500
    }
    if (position === 7. && league === 'epl') return {
        borderBottom: '1px solid #f97316',           // orange-500
        backgroundColor: 'rgba(67, 20, 7, 0.4)',
        borderLeft: '4px solid #f97316'             // orange-500
    }
    if (position === 8 && league === 'epl') return {
        borderBottom: '1px solid #22c55e',           // green-500
        backgroundColor: 'rgba(5, 46, 22, 0.4)',    // green-950 at 40% opacity
        borderLeft: '4px solid #22c55e'              // green-500
    }
    if (league === 'ligue1' || league === 'bundesliga') {
        if (position === 16) return {
            borderTop: '2px solid #ef4444',             // red-500
            borderBottom: '1px solid #f87171',          // red-400
            backgroundColor: 'rgba(254, 202, 202, 0.4)', // red-200 at 40% opacity
            borderLeft: '4px solid #ef4444'             // red-500
        }

        if (position >= 16) return {
            borderBottom: '1px solid #f87171',          // red-400
            backgroundColor: 'rgba(254, 202, 202, 0.4)', // red-200 at 40% opacity
            borderLeft: '4px solid #ef4444'             // red-500
        }
    }
    if (position === 18) return { borderTop: '2px solid #ef4444', borderBottom: '1px solid #f87171', borderLeft: '4px solid #ef4444', backgroundColor: 'rgba(69, 10, 10, 0.4)' } // red-500
    if (position >= 18) return {
        borderBottom: '1px solid #f87171',
        backgroundColor: 'rgba(69, 10, 10, 0.4)',
        borderLeft: '4px solid #ef4444'              // red-500
    }
    return {borderBottom: `1px solid ${theme.border}`, backgroundColor: `${theme.background}`}; // default row style
};

export default function StandingsTab({ lastUpdate, league = 'epl', theme }) {
    const [standings, setStandings] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    const fetchStandings = useCallback(async () => {
        try {
            const response = await fetch(`${process.env.REACT_APP_API_URL || 'http://localhost:8000'}/standings?league=${league}`)
            const data = await response.json()
            setStandings(data)
            setLoading(false)
        } catch (err) {
            setError(err.message)
            setLoading(false)
        }
    }, [league])

    useEffect(() => {
        fetchStandings()
    }, [fetchStandings])
    
    useEffect(() => {
        if (lastUpdate?.type === 'standings') {
            fetchStandings()
        }
    }, [lastUpdate, fetchStandings])
    
    useEffect(() => {
        const interval = setInterval(fetchStandings, 60 * 1000) // Poll every 60 seconds
        return () => clearInterval(interval)
    }, [fetchStandings])

    if (loading) return <div className="text-[#37003c] p-4">Loading standings...</div>
    if (error)   return <div className="text-[#37003c]" p-4>Error: {error}</div>
    if (!standings?.length) return <div className="text-[#37003c] p-4">No standings data available.</div>
    
    return (
        <div className='max-w-6xl mx-auto'>
            
            <div className='flex gap-6 items-start'>
                {/* TABLE */}
                <div style={{ backgroundColor: theme.secondary, borderColor: theme.border }}
                    className="rounded-lg border overflow-hidden"
                >

                    {/* Header */}
                    <div 
                        className="grid grid-cols-12 gap-2 px-6 py-4 text-sm font-semibold uppercase tracking-wider border-b"
                        style={{ color: theme.text, borderColor: theme.border }}
                    >
                        <div className="col-span-1 text-center">#</div>
                        <div className="col-span-4">Team</div>
                        <div className="col-span-1 text-center">MP</div>
                        <div className="col-span-1 text-center">W</div>
                        <div className="col-span-1 text-center">D</div>
                        <div className="col-span-1 text-center">L</div>
                        <div className="col-span-1 text-center">GD</div>
                        <div className="col-span-1 text-center">GF - GA</div>
                        <div className="col-span-1 text-center font-bold">Pts</div>
                    </div>

                    {/* Rows */}
                    {standings.map((team, index) => {
                        const position = index + 1
                        return (
                            <div
                                key={team.team_name}
                                style={rowColors(position, theme, league)}
                                className={`grid grid-cols-12 gap-2 px-6 py-4 items-center text-base hover:opacity-80 transition-colors duration-300`}
                            >
                                
                                <div className="col-span-1 text-center text-white text-lg font-medium">{position}</div>
                                <div 
                                    className="col-span-4 flex items-center gap-3 font-medium"
                                    style={{ color: theme.text }}
                                >
                                    <div className="w-9 h-9 rounded-full bg-white flex items-center justify-center flex-shrink-0">
                                        <img
                                            src={`https://a.espncdn.com/i/teamlogos/soccer/500/${team.team_id}.png`}
                                            alt={team.team_name}
                                            className="w-7 h-7 object-contain"
                                            onError={(e) => {e.target.style.display = 'none'}}
                                        />
                                    </div>
                                    {team.team_name}
                                </div>
                                <div className="col-span-1 text-center" style={{ color: theme.text }}>
                                    {team.matches_played}
                                </div>
                                <div className="col-span-1 text-center" style={{ color: theme.text }}>
                                    {team.wins}
                                </div>
                                <div className="col-span-1 text-center" style={{ color: theme.text }}>
                                    {team.draws}
                                </div>
                                <div className="col-span-1 text-center" style={{ color: theme.text }}>
                                    {team.losses}
                                </div>
                                <div className={`col-span-1 text-center ${
                                    team.goal_diff > 0 ? 'text-[#00ff85]' :
                                    team.goal_diff < 0 ? 'text-red-300' :
                                    'text-purple-200'
                                }`} style={{ color: theme.text }}>
                                    {team.goal_diff > 0 ? `+${team.goal_diff}` : team.goal_diff}
                                </div>
                                <div className="col-span-1 text-center" style={{ color: theme.text }}>
                                    {team.goals_for} - {team.goals_against}
                                </div>
                                <div className="col-span-1 text-center font-bold" style={{ color: theme.text }}>
                                    {team.points}
                                </div>
                            </div>
                        )
                    })}
                </div>

                {/* Legend */}
                <div className="flex-shrink-0 flex flex-col gap-3 pt-2 text-xs text-[#37003c] ml-4">
                    <span className="font-semibold uppercase tracking-wider text-[#37003c] mb-1">
                        Zones
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="w-8 h-1 bg-blue-500 inline-block rounded-full" />
                        {league === 'epl' || league === 'laliga' ? 'UEFA Champions League (1-5)' : 'UEFA Champions League (1-4)'}
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="w-8 h-1 bg-orange-500 inline-block rounded-full" />
                        {league === 'bundesliga' || league === 'seriea' ? 'UEFA Europa League (5-6)' :
                            league === 'laliga' ? 'UEFA Europa League (6)' : 
                            league === 'epl' ? 'UEFA Europa League (6-7)' : 'UEFA Europa League (5)'}
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="w-8 h-1 bg-green-500 inline-block rounded-full" />
                        {league === 'ligue1'? 'UEFA Conference League (6)' : 
                        league === 'laliga' || league === 'seriea' || league === 'bundesliga' ? 'UEFA Conference League (7)' : 'UEFA Conference League (8)'}
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="w-8 h-1 bg-red-500 inline-block rounded-full" />
                        {league === 'epl' || league === 'laliga' || league === 'seriea' ? 'Relegation (18-20)' : 'Relegation (16-18)'}
                    </span>
                </div>
            </div>
            
            {/* Last updated */}
            <div className="mt-3 text-xs text-[#37003c] text-right opacity-60">
                Updates every 5 minutes
            </div>
        </div>
    )
}