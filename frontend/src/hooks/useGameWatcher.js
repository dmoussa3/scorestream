import { useEffect, useRef } from "react";

const LIVE_STATUSES = ['STATUS_IN_PROGRESS', 'STATUS_HALFTIME', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF']

export function useGameWatcher(games, notify) {
    const prevGamesRef = useRef({})

    useEffect(() => {
        if (!games?.length) return

        games.forEach(game => {
            const prev = prevGamesRef.current[game.game_id]

            if (!prev) {
                prevGamesRef.current[game.game_id] = game
                return
            }

            // GOAL EVENTS

            const prevHomeScore = prev.home_score || 0
            const prevAwayScore = prev.away_score || 0
            const newHomeScore = game.home_score || 0
            const newAwayScore = game.away_score || 0

            if (newHomeScore != prevHomeScore) {
                notify(
                    `⚽ Goal — ${game.home_team}`,
                    `${game.home_team} ${newHomeScore} – ${newAwayScore} ${game.away_team}`,
                    `https://a.espncdn.com/i/teamlogos/soccer/500/${game.home_id}.png`
                )
            }

            if (newAwayScore != prevAwayScore) {
                notify(
                    `⚽ Goal — ${game.away_team}`,
                    `${game.home_team} ${newHomeScore} – ${newAwayScore} ${game.away_team}`,
                    `https://a.espncdn.com/i/teamlogos/soccer/500/${game.away_id}.png`
                )
            }

            // STATUS CHANGES

            if (game.status !== prev.status) {

                // Kickoff
                if (game.status === 'STATUS_IN_PROGRESS' && !LIVE_STATUSES.includes(prev.status)) {
                    notify(
                        `🟢 Kickoff`,
                        `${game.home_team} vs ${game.away_team} has started`,
                        `https://a.espncdn.com/i/teamlogos/soccer/500/${game.home_id}.png`
                    )
                }

                // Halftime
                if (game.status === 'STATUS_HALFTIME') {
                    notify(
                        `⏸ Halftime`,
                        `${game.home_team} ${newHomeScore} – ${newAwayScore} ${game.away_team} is at halftime`,
                        `https://a.espncdn.com/i/teamlogos/soccer/500/${game.home_id}.png`
                    )
                }

                // Full-time
                if (game.status === 'STATUS_FULL_TIME' || game.status === 'STATUS_FINAL') {
                    notify(
                        `🏁 Full Time`,
                        `${game.home_team} ${newHomeScore} – ${newAwayScore} ${game.away_team}`,
                        `https://a.espncdn.com/i/teamlogos/soccer/500/${game.home_id}.png`
                    )
                }

                // Second-half start
                if (game.status === 'STATUS_SECOND_HALF' && prev.status === 'STATUS_HALFTIME') {
                    notify(
                        `🟣 Second Half`,
                        `${game.home_team} ${newHomeScore} – ${newAwayScore} ${game.away_team} -- Second half started`,
                        `https://a.espncdn.com/i/teamlogos/soccer/500/${game.home_id}.png`
                    )
                }

                prevGamesRef.current[game.game_id] = game
            }
        })
    }, [games])
}