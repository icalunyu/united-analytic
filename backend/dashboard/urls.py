from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('jadwal/', views.schedule, name='schedule'),
    path('pra/', views.pre_match, name='pre_match'),
    path('match/<int:match_id>/', views.match_detail, name='match_detail'),
    path('skuad/', views.squad, name='squad'),
    path('statistik/', views.statistics, name='statistics'),
    path('berita/', views.news, name='news'),
    path('cedera/', views.injuries, name='injuries'),
]
