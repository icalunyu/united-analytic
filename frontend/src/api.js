const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export async function fetchMatches(params = {}) {
  const url = new URL('/api/matches/', API_BASE_URL)
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, value)
    }
  })

  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Gagal ambil data jadwal (HTTP ${response.status})`)
  }

  return response.json()
}
