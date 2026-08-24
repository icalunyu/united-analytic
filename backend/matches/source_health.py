"""Kesegaran tiap feed, dihitung dari catatan penarikan.

Fondasi kartu Kesehatan Sumber dan indikator di bar atas. Yang ditampilkan
handoff: titik hijau/kuning/merah plus keterangan macam "6 jam tanpa data
baru", dan legenda arti warnanya wajib ikut tampil.

Aturan warnanya sengaja per-sumber, bukan satu ambang untuk semua: sumber
harian (Understat, FotMob) normal kalau terakhir menarik 1 hari lalu,
sementara ESPN yang jalan tiap 10 menit di jendela laga sudah patut dicurigai
kalau diam 3 jam.
"""

from django.utils import timezone

from matches.models import MatchIngest, SourceHeartbeat
from players.models import DataSource

# Ambang per sumber dalam jam: (masih normal, mulai patut dicurigai).
# Di atas ambang kedua = merah, angkanya jangan dipakai sebelum dicek manual.
THRESHOLDS = {
    DataSource.ESPN: (3, 12),
    DataSource.FOTMOB: (26, 72),
    DataSource.UNDERSTAT: (26, 72),
    DataSource.PREMIER_LEAGUE: (26, 72),
    DataSource.FOOTBALL_DATA: (6, 24),
    DataSource.HIGHLIGHTLY: (26, 72),
    DataSource.THESPORTSDB: (26, 72),
}
DEFAULT_THRESHOLD = (26, 72)


def _describe(hours):
    if hours is None:
        return 'belum pernah menarik'
    if hours < 1:
        return f'{int(hours * 60)} menit lalu'
    if hours < 48:
        return f'{int(hours)} jam lalu'
    return f'{int(hours // 24)} hari lalu'


def source_health(sources=None):
    """Status tiap sumber, urut dari yang paling perlu perhatian.

    Return list dict: source, label, status ('normal'|'lambat'|'berhenti'),
    last_at, hours, description, matches.
    """
    tracked = sources or [
        DataSource.FOTMOB,
        DataSource.UNDERSTAT,
        DataSource.ESPN,
        DataSource.PREMIER_LEAGUE,
    ]
    now = timezone.now()
    rows = []

    for source in tracked:
        latest = MatchIngest.objects.filter(source=source).order_by('-ingested_at').first()
        terakhir = latest.ingested_at if latest else None

        # Heartbeat menang kalau lebih baru. Sesudah penyaring inkremental,
        # feed yang sehat bisa berhari-hari nggak nambah MatchIngest karena
        # emang nggak ada laga baru — dan itu jawaban yang SAH, bukan mati.
        beat = SourceHeartbeat.objects.filter(source=source).first()
        if beat and (terakhir is None or beat.last_ok_at > terakhir):
            terakhir = beat.last_ok_at

        hours = (now - terakhir).total_seconds() / 3600 if terakhir else None
        warn, stop = THRESHOLDS.get(source, DEFAULT_THRESHOLD)

        if hours is None or hours >= stop:
            status = 'berhenti'
        elif hours >= warn:
            status = 'lambat'
        else:
            status = 'normal'

        rows.append({
            'source': source,
            'label': DataSource(source).label.split(' (')[0],
            'status': status,
            'last_at': terakhir,
            'hours': hours,
            'description': _describe(hours),
            'matches': MatchIngest.objects.filter(source=source).count(),
        })

    order = {'berhenti': 0, 'lambat': 1, 'normal': 2}
    rows.sort(key=lambda r: (order[r['status']], -(r['hours'] or 1e9)))
    return rows
