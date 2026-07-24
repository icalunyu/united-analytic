from rest_framework import serializers

from .models import Injury, Player


class PlayerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Player
        fields = [
            'id',
            'name',
            'first_name',
            'last_name',
            'nationality',
            'birth_date',
            'position',
            'shirt_number',
            'height_cm',
            'weight_kg',
            'photo_url',
            'on_loan',
            'is_active',
        ]


class InjurySerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(source='player.name')
    player_photo_url = serializers.CharField(source='player.photo_url')

    class Meta:
        model = Injury
        fields = [
            'id',
            'player_name',
            'player_photo_url',
            'reason',
            'status',
            'start_date',
            'expected_return_date',
            'actual_return_date',
        ]
