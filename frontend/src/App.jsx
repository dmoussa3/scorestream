import { useState, useEffect } from 'react'
import ScoresTab from './components/ScoresTab'
import StandingsTab from './components/StandingsTab'
import PipelineTab from './components/PipelineTab'
import MatchesTab from './components/MatchesTab'

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000'

export default function App() {
  const [activeTab, setActiveTab] = useState('scores')
  const [apiStatus, setApiStatus] = useState('checking...')
  const [selectedGameId, setSelectedGameId] = useState(null)

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
        <h1 className="text-xl font-bold text-white">⚽ ScoreStream 🇬🇧</h1>
        <span className={`absolute right-6 text-sm px-2 py-1 rounded ${
          apiStatus === 'connected' ? 'bg-[#00ff85] text-[#37003c] font-semibold' :
          apiStatus === 'unreachable' ? 'bg-red-900 text-red-300' :
          'bg-yellow-900 text-yellow-300'
        }`}>
          API: {apiStatus}
        </span>
      </header>

      {/* Tab navigation */}
      <nav className="bg-[#2d0032] border-b border-purple-900 px-6">
        <div className="flex gap-1 justify-center">
          {tabs.map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-3 text-sm font-medium capitalize border-b-2 transition-colors ${
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
      </nav>

      {/* Tab content — placeholders for now */}
      <main className="p-6 bg-white">
        {activeTab === 'scores' && (
          <ScoresTab onSelectGame={handleSelectedGame} />
        )}
        {activeTab === 'standings' && <StandingsTab />}
        {activeTab === 'match' && (
          <MatchesTab gameId={selectedGameId} onBack={() => setActiveTab('scores')} />
        )}
        {activeTab === 'pipeline' && <PipelineTab />}
      </main>

    </div>
  )
}