const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

function buildUrl(path, params = {}) {
  const url = new URL(path, API_BASE_URL)
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, value)
    }
  })
  return url
}

async function getJson(url, errorLabel) {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`${errorLabel} (HTTP ${response.status})`)
  }
  return response.json()
}

export function fetchMatches(params = {}) {
  return getJson(buildUrl('/api/matches/', params), 'Gagal ambil data jadwal')
}

export function fetchMatchDetail(id) {
  return getJson(buildUrl(`/api/matches/${id}/`), 'Gagal ambil detail match')
}

export function fetchPlayers(params = {}) {
  return getJson(buildUrl('/api/players/', params), 'Gagal ambil data skuad')
}

export function fetchInjuries(params = {}) {
  return getJson(buildUrl('/api/injuries/', params), 'Gagal ambil data cedera')
}

export function fetchUrl(url) {
  return getJson(url, 'Gagal ambil data')
}
