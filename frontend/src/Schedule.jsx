import { useEffect, useState } from 'react'
import { fetchMatches } from './api'
import MatchDetail from './MatchDetail'

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

const LIVE_STATUSES = ['LIVE', 'HT']

function LiveBadge() {
  return <span className="live-badge">● LIVE</span>
}

function MatchCard({ match, onSelect }) {
  const isLive = LIVE_STATUSES.includes(match.status)

  return (
    <li className="match-card match-card-clickable" onClick={() => onSelect(match.id)}>
      <div className="match-competition">
        {isLive && <LiveBadge />}
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

function Schedule() {
  const [matches, setMatches] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [selectedMatchId, setSelectedMatchId] = useState(null)

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

  if (selectedMatchId) {
    return <MatchDetail matchId={selectedMatchId} onBack={() => setSelectedMatchId(null)} />
  }

  if (status === 'loading') return <p className="state-message">Memuat jadwal...</p>
  if (status === 'error') {
    return <p className="state-message error">Gagal memuat jadwal: {error}</p>
  }
  if (matches.length === 0) {
    return <p className="state-message">Belum ada jadwal pertandingan mendatang di database.</p>
  }

  return (
    <ul className="match-list">
      {matches.map((match) => (
        <MatchCard key={match.id} match={match} onSelect={setSelectedMatchId} />
      ))}
    </ul>
  )
}

export default Schedule
