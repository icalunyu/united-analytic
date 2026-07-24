import { useEffect, useState } from 'react'
import { fetchInjuries, fetchUrl } from './api'

function formatDate(value) {
  if (!value) return null
  return new Date(value).toLocaleDateString('id-ID', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

const STATUS_LABEL = {
  OUT: 'Absen',
  DOUBTFUL: 'Diragukan',
  RETURNED: 'Sudah Pulih',
}

function InjuryRow({ injury }) {
  const start = formatDate(injury.start_date)
  const end = formatDate(injury.actual_return_date) || formatDate(injury.expected_return_date)

  return (
    <li className="injury-row">
      <div className="injury-player">
        {injury.player_photo_url && (
          <img src={injury.player_photo_url} alt={injury.player_name} className="injury-photo" />
        )}
        <span>{injury.player_name}</span>
      </div>
      <div className="injury-reason">{injury.reason}</div>
      <div className="injury-dates">
        {start}
        {end ? ` – ${end}` : ''}
      </div>
      <div className={`injury-status status-${injury.status.toLowerCase()}`}>
        {STATUS_LABEL[injury.status] ?? injury.status}
      </div>
    </li>
  )
}

function Injuries() {
  const [injuries, setInjuries] = useState([])
  const [nextUrl, setNextUrl] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [loadingMore, setLoadingMore] = useState(false)

  useEffect(() => {
    let cancelled = false

    fetchInjuries()
      .then((data) => {
        if (cancelled) return
        setInjuries(data.results ?? [])
        setNextUrl(data.next)
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

  const loadMore = () => {
    if (!nextUrl) return
    setLoadingMore(true)
    fetchUrl(nextUrl)
      .then((data) => {
        setInjuries((prev) => [...prev, ...(data.results ?? [])])
        setNextUrl(data.next)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoadingMore(false))
  }

  if (status === 'loading') return <p className="state-message">Memuat riwayat cedera...</p>
  if (status === 'error') {
    return <p className="state-message error">Gagal memuat riwayat cedera: {error}</p>
  }
  if (injuries.length === 0) {
    return <p className="state-message">Belum ada data cedera di database.</p>
  }

  return (
    <div>
      <ul className="injury-list">
        {injuries.map((injury) => (
          <InjuryRow key={injury.id} injury={injury} />
        ))}
      </ul>

      {nextUrl && (
        <button type="button" className="load-more-button" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? 'Memuat...' : 'Muat lebih banyak'}
        </button>
      )}
    </div>
  )
}

export default Injuries
