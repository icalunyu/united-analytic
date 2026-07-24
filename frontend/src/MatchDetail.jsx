import { useEffect, useState } from 'react'
import { fetchMatchDetail } from './api'

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

function eventIcon(eventType) {
  switch (eventType) {
    case 'GOAL':
      return '⚽'
    case 'CARD':
      return '🟨'
    case 'SUBST':
      return '🔄'
    case 'VAR':
      return '📺'
    default:
      return '•'
  }
}

function eventDescription(event) {
  if (event.event_type === 'GOAL') {
    return event.assist_player_name
      ? `${event.player_name} (assist: ${event.assist_player_name})`
      : event.player_name
  }
  if (event.event_type === 'SUBST') {
    return event.assist_player_name
      ? `${event.player_name} masuk gantiin ${event.assist_player_name}`
      : `${event.player_name} masuk`
  }
  return event.player_name || event.detail
}

function EventRow({ event }) {
  const minuteLabel = event.extra_minute
    ? `${event.minute}+${event.extra_minute}'`
    : `${event.minute}'`

  return (
    <li className="event-row">
      <span className="event-minute">{minuteLabel}</span>
      <span className="event-icon">{eventIcon(event.event_type)}</span>
      <span className={event.team?.is_manchester_united ? 'event-desc mu' : 'event-desc'}>
        {eventDescription(event)}
      </span>
    </li>
  )
}

function MatchDetail({ matchId, onBack }) {
  const [match, setMatch] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setStatus('loading')

    fetchMatchDetail(matchId)
      .then((data) => {
        if (cancelled) return
        setMatch(data)
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
  }, [matchId])

  return (
    <div>
      <button type="button" className="back-button" onClick={onBack}>
        ← Kembali ke jadwal
      </button>

      {status === 'loading' && <p className="state-message">Memuat detail match...</p>}

      {status === 'error' && (
        <p className="state-message error">Gagal memuat detail match: {error}</p>
      )}

      {status === 'ready' && match && (
        <div className="match-detail">
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
            {match.referee && <span> · Wasit: {match.referee}</span>}
          </div>

          <h2 className="events-heading">Jalannya Pertandingan</h2>
          {match.events.length === 0 ? (
            <p className="state-message">Belum ada data event buat match ini.</p>
          ) : (
            <ul className="event-list">
              {match.events.map((event) => (
                <EventRow key={event.id} event={event} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

export default MatchDetail
