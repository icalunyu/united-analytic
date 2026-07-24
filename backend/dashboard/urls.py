from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('jadwal/', views.schedule, name='schedule'),
    path('match/<int:match_id>/', views.match_detail, name='match_detail'),
    path('skuad/', views.squad, name='squad'),
    path('cedera/', views.injuries, name='injuries'),
]
