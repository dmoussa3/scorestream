import { useWebSocket } from "../hooks/useWebSocket";
import { useCallback, useEffect, useState } from "react";

const rowColors = (position) => {
    if (position === 1) { return 'border-l-4 border-b-2 border-blue-500 bg-blue-950/40'; }
    if (position <= 5) { return 'border-l-4 border-t-2 border-b-2 border-blue-500 bg-blue-950/40'; }
    if (position === 6) { return 'border-l-4 border-b-2 border-orange-500 bg-orange-950/40'; }
    if (position === 7) { return 'border-l-4 border-b-2 border-green-500 bg-green-950/40'; }
    if (position >= 18) { return 'border-l-4 border-b-2 border-t-2 border-red-400 bg-red-950/40'; }
    return 'border-b-2 border-purple-800'; // default row style
};

export default function StandingsTab({ lastUpdate}) {
    const [standings, setStandings] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    const fetchStandings = useCallback(async () => {
        try {
        const response = await fetch(`${process.env.REACT_APP_API_URL || 'http://localhost:8000'}/standings`)
            const data = await response.json()
            setStandings(data)
            setLoading(false)
        } catch (err) {
            setError(err.message)
        }
    }, [])

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
                <div className="bg-[#2d0032] rounded-lg border border-[#00ff85] overflow-hidden">

                    {/* Header */}
                    <div className="grid grid-cols-12 gap-2 px-6 py-4 text-sm font-semibold text-purple-400 uppercase tracking-wider border-b border-purple-800">
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
                                className={`grid grid-cols-12 gap-2 px-6 py-4 text-base hover:bg-[#3d0048] transition-colors ${rowColors(position)}`}
                            >
                                
                                <div className="col-span-1 text-center text-white font-medium">{position}</div>
                                <div className="col-span-4 flex items-center gap-3 font-medium text-white">
                                    <div className="w-8 h-8 rounded-full bg-white flex items-center justify-center flex-shrink-0">
                                        <img
                                            src={`https://a.espncdn.com/i/teamlogos/soccer/500/${team.team_id}.png`}
                                            alt={team.team_name}
                                            className="w-7 h-7 object-contain"
                                            onError={(e) => {e.target.style.display = 'none'}}
                                        />
                                    </div>
                                    {team.team_name}
                                </div>
                                <div className="col-span-1 text-center text-white">{team.matches_played}</div>
                                <div className="col-span-1 text-center text-white">{team.wins}</div>
                                <div className="col-span-1 text-center text-white">{team.draws}</div>
                                <div className="col-span-1 text-center text-white">{team.losses}</div>
                                <div className={`col-span-1 text-center ${
                                    team.goal_diff > 0 ? 'text-[#00ff85]' :
                                    team.goal_diff < 0 ? 'text-red-300' :
                                    'text-purple-200'
                                }`}>
                                    {team.goal_diff > 0 ? `+${team.goal_diff}` : team.goal_diff}
                                </div>
                                <div className="col-span-1 text-center text-white">{team.goals_for} - {team.goals_against}</div>
                                <div className="col-span-1 text-center font-bold text-white text-lg">{team.points}</div>
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
                        UEFA Champions League (1-5)
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="w-8 h-1 bg-orange-500 inline-block rounded-full" />
                        UEFA Europa League (6)
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="w-8 h-1 bg-green-500 inline-block rounded-full" />
                        UEFA Conference League (7)
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="w-8 h-1 bg-red-500 inline-block rounded-full" />
                        Relegation (18-20)
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