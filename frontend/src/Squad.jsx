import { useEffect, useState } from 'react'
import { fetchPlayers } from './api'

const POSITION_GROUPS = [
  { label: 'Kiper', codes: ['GK'] },
  { label: 'Bek', codes: ['CB', 'RB', 'LB'] },
  { label: 'Gelandang', codes: ['CDM', 'CM', 'CAM'] },
  { label: 'Penyerang', codes: ['WNG', 'CF'] },
]

function groupByPosition(players) {
  const groups = POSITION_GROUPS.map((g) => ({ ...g, players: [] }))
  const others = []

  for (const player of players) {
    const group = groups.find((g) => g.codes.includes(player.position))
    if (group) {
      group.players.push(player)
    } else {
      others.push(player)
    }
  }

  if (others.length > 0) {
    groups.push({ label: 'Lainnya', codes: [], players: others })
  }

  return groups.filter((g) => g.players.length > 0)
}

function PlayerCard({ player }) {
  return (
    <li className="player-card">
      <div className="player-photo">
        {player.photo_url ? (
          <img src={player.photo_url} alt={player.name} loading="lazy" />
        ) : (
          <div className="player-photo-placeholder">{player.shirt_number ?? '?'}</div>
        )}
      </div>
      <div className="player-info">
        <div className="player-name">{player.name}</div>
        <div className="player-meta">
          {player.shirt_number ? `#${player.shirt_number} · ` : ''}
          {player.nationality}
        </div>
      </div>
    </li>
  )
}

function Squad() {
  const [players, setPlayers] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    fetchPlayers()
      .then((data) => {
        if (cancelled) return
        setPlayers(data.results ?? [])
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

  if (status === 'loading') return <p className="state-message">Memuat skuad...</p>
  if (status === 'error') {
    return <p className="state-message error">Gagal memuat skuad: {error}</p>
  }
  if (players.length === 0) {
    return <p className="state-message">Belum ada data skuad di database.</p>
  }

  const groups = groupByPosition(players)

  return (
    <div>
      {groups.map((group) => (
        <section key={group.label} className="squad-group">
          <h2 className="squad-group-heading">{group.label}</h2>
          <ul className="player-list">
            {group.players.map((player) => (
              <PlayerCard key={player.id} player={player} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

export default Squad
