import { useState, useEffect, useCallback } from 'react'
import ScoresTab from './components/ScoresTab'
import StandingsTab from './components/StandingsTab'
import PipelineTab from './components/PipelineTab'
import MatchesTab from './components/MatchesTab'
import { useWebSocket } from './hooks/useWebSocket'

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000'

const LEAGUES_NAMES = {
	'epl': 'English Premier League 🇬🇧',
	'laliga': 'La Liga 🇪🇸',
	'bundesliga': 'Bundesliga 🇩🇪',
	'seriea': 'Serie A 🇮🇹',
	'ligue1': 'Ligue 1 🇫🇷'
}

export default function App() {
	const [activeTab, setActiveTab] = useState('scores')
	const [apiStatus, setApiStatus] = useState('checking...')
	const [selectedGameId, setSelectedGameId] = useState(null)
	const [lastUpdate, setLastUpdate] = useState(null)
	const [selectedLeague, setSelectedLeague] = useState('epl')
	const [availableLeagues, setAvailableLeagues] = useState(['epl'])

	useEffect(() => {
		fetch(`${API}/leagues`)
		.then(res => res.json())
		.then(setAvailableLeagues)
		.catch(() => {})
	}, [])

	const handleWebSocketMessage = useCallback((message) => {
		setLastUpdate(message)
	}, [])

	const { isConnected: connected } = useWebSocket(handleWebSocketMessage)
	
	const handleSelectedGame = (gameId) => {
		setSelectedGameId(gameId)
		setActiveTab('match')
	}

	useEffect(() => {
		fetch(`${API}/health`)
		.then(res => res.json())
		.then(data => setApiStatus(data.api === 'ok' ? 'connected' : 'degraded'))
		.catch(() => setApiStatus('unreachable'))
	}, [])

	const tabs = ['scores', 'standings', 'match', 'pipeline']

	return (
		<div className="min-h-screen bg-white text-[#37003c]">

			{/* Header */}
			<header className="bg-[#2d0032] border-b border-[#00ff85] px-6 py-4 flex items-center justify-center relative">
			<h1 className="text-xl font-bold text-white">⚽ ScoreStream ⚽</h1>

			<div className='absolute right-6 flex items-center gap-2'>
				{/* WebSocket connection indicator */}
				<span className={`text-xs px-2 py-1 rounded font-medium ${
					connected
						? 'bg-[#00ff85] text-[#37003c]'
						: 'bg-red-900 text-red-300'
				}`}>
					{connected ? '🟢 WebSocket Live' : '🔴 Reconnecting...'}
				</span>
				<span className={`text-sm px-2 py-1 rounded ${
						apiStatus === 'connected' ? 'bg-[#00ff85] text-[#37003c] font-semibold' :
						apiStatus === 'unreachable' ? 'bg-red-900 text-red-300' :
						'bg-yellow-900 text-yellow-300'
				}`}>
					API: {apiStatus}
				</span>
			</div>
			</header>

			{/* Tab navigation */}
			<nav className="bg-[#2d0032] border-b border-purple-900 px-6 py-3">
				<div className="flex flex-col items-center gap-3 py-1">

					<div className='flex gap-1'>
						{tabs.map(tab => (
						<button
							key={tab}
							onClick={() => setActiveTab(tab)}
							className={`px-4 py-1 text-sm font-medium capitalize border-b-2 transition-colors ${
							activeTab === tab
								? 'border-[#00ff85] text-[#00ff85]'
								: 'border-transparent text-purple-300 hover:text-white'
							}`}
						>
							{tab === 'match' ? 'Match Detail' :
							tab === 'pipeline' ? 'Pipeline Health' : tab}
						</button>
						))}
					</div>

					{/* League selector - only show on scores and standings tab */}
					{(activeTab === 'scores' || activeTab === 'standings') && (
						<div className='flex items-center gap-2'>
							{availableLeagues.map(l => (
								<button
									key={l}
									onClick={() => setSelectedLeague(l)}
									className={`text-xs px-3 py-1 rounded-full font-medium capitalize transition-colors ${
										selectedLeague === l
											? 'bg-[#00ff85] text-[#37003c]'
											: 'bg-purple-900 text-purple-300 hover:text-white'
									}`}
								>
									{LEAGUES_NAMES[l] || l.toUpperCase()}
								</button>
							))}
						</div>
					)}
				</div>
			</nav>

			{/* Tab content */}
			<main className="p-6 bg-white">
			{activeTab === 'scores' && (
				<ScoresTab onSelectGame={handleSelectedGame} lastUpdate={lastUpdate} league={selectedLeague} />
			)}
			{activeTab === 'standings' && <StandingsTab lastUpdate={lastUpdate} league={selectedLeague} />}
			{activeTab === 'match' && (
				<MatchesTab gameId={selectedGameId} onBack={() => setActiveTab('scores')} />
			)}
			{activeTab === 'pipeline' && <PipelineTab active={activeTab === 'pipeline'} />}
			</main>

		</div>
	)
}