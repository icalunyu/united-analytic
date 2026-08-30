from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('jadwal/', views.schedule, name='schedule'),
    path('pra/', views.pre_match, name='pre_match'),
    path('pasca/', views.post_match, name='post_match'),
    path('match/<int:match_id>/', views.match_detail, name='match_detail'),
    path('skuad/', views.squad, name='squad'),
    path('statistik/', views.statistics, name='statistics'),
    path('berita/', views.news, name='news'),
    path('cedera/', views.injuries, name='injuries'),
    # Aksi. Semuanya POST — pilihan analis dan centang momen mengubah keadaan,
    # dan keadaan yang bisa diubah lewat URL yang di-share itu jebakan.
    path(
        'skuad/<int:player_id>/putuskan/',
        views.availability_decide,
        name='availability_decide',
    ),
    path(
        'skuad/<int:player_id>/batalkan/',
        views.availability_reset,
        name='availability_reset',
    ),
    path(
        'pra/hipotesis/<int:item_id>/pilih/',
        views.hypothesis_toggle,
        name='hypothesis_toggle',
    ),
    path('pasca/<int:match_id>/momen/', views.moment_add, name='moment_add'),
    path('momen/<int:moment_id>/centang/', views.moment_toggle, name='moment_toggle'),
    path('momen/<int:moment_id>/hapus/', views.moment_delete, name='moment_delete'),
]
