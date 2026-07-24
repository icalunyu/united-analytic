from rest_framework import serializers

from players.models import Team

from .models import Match, MatchEvent, MatchTeamStatistics


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = [
            'id',
            'name',
            'short_name',
            'code',
            'logo_url',
            'is_manchester_united',
        ]


class MatchEventSerializer(serializers.ModelSerializer):
    team = TeamSerializer(read_only=True)
    player_name = serializers.CharField(source='player.name', default=None)
    assist_player_name = serializers.CharField(source='assist_player.name', default=None)

    class Meta:
        model = MatchEvent
        fields = [
            'id',
            'event_type',
            'detail',
            'minute',
            'extra_minute',
            'team',
            'player_name',
            'assist_player_name',
        ]


class MatchListSerializer(serializers.ModelSerializer):
    home_team = TeamSerializer(read_only=True)
    away_team = TeamSerializer(read_only=True)

    class Meta:
        model = Match
        fields = [
            'id',
            'league_name',
            'season',
            'round',
            'home_team',
            'away_team',
            'kickoff_at',
            'venue',
            'status',
            'home_score',
            'away_score',
        ]


class MatchTeamStatisticsSerializer(serializers.ModelSerializer):
    team = TeamSerializer(read_only=True)

    class Meta:
        model = MatchTeamStatistics
        fields = [
            'team',
            'possession_pct',
            'shots_total',
            'shots_on_target',
            'corners',
            'fouls',
            'offsides',
            'yellow_cards',
            'red_cards',
            'passes_total',
            'passes_accurate',
            'saves',
        ]


class MatchDetailSerializer(MatchListSerializer):
    events = MatchEventSerializer(many=True, read_only=True)
    team_statistics = MatchTeamStatisticsSerializer(many=True, read_only=True)

    class Meta(MatchListSerializer.Meta):
        fields = MatchListSerializer.Meta.fields + ['referee', 'events', 'team_statistics']
