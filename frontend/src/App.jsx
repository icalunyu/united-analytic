import { useEffect, useState } from 'react'
import './App.css'
import { fetchMatches } from './api'

function formatKickoff(isoString) {
  return new Date(isoString).toLocaleString('id-ID', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function MatchCard({ match }) {
  return (
    <li className="match-card">
      <div className="match-competition">
        {match.league_name}
        {match.round ? ` · ${match.round}` : ''}
      </div>
      <div className="match-teams">
        <span className={match.home_team.is_manchester_united ? 'team mu' : 'team'}>
          {match.home_team.name}
        </span>
        <span className="score">
          {match.home_score !== null && match.away_score !== null
            ? `${match.home_score} - ${match.away_score}`
            : 'vs'}
        </span>
        <span className={match.away_team.is_manchester_united ? 'team mu' : 'team'}>
          {match.away_team.name}
        </span>
      </div>
      <div className="match-meta">
        <span>{formatKickoff(match.kickoff_at)}</span>
        {match.venue && <span> · {match.venue}</span>}
      </div>
    </li>
  )
}

function App() {
  const [matches, setMatches] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    fetchMatches()
      .then((data) => {
        if (cancelled) return
        setMatches(data.results ?? [])
        setStatus('ready')
      })
      .catch((err) => {
        if (cancelled) return
        setError(err.message)
        setStatus('error')
      })

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="page">
      <header className="page-header">
        <h1>Jadwal Manchester United</h1>
        <p>MU Analytics — IndoManUtd Jogja</p>
      </header>

      <main>
        {status === 'loading' && <p className="state-message">Memuat jadwal...</p>}

        {status === 'error' && (
          <p className="state-message error">
            Gagal memuat jadwal: {error}
          </p>
        )}

        {status === 'ready' && matches.length === 0 && (
          <p className="state-message">
            Belum ada jadwal pertandingan mendatang di database.
          </p>
        )}

        {status === 'ready' && matches.length > 0 && (
          <ul className="match-list">
            {matches.map((match) => (
              <MatchCard key={match.id} match={match} />
            ))}
          </ul>
        )}
      </main>
    </div>
  )
}

export default App
