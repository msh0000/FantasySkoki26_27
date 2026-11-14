from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("druzyna/", views.team, name="team"),
    path("druzyna/<int:player_id>/", views.team, name="team_of"),
    path("weekendy/", views.weekends, name="weekends"),
    path("weekendy/<int:pk>/", views.weekend_detail, name="weekend_detail"),
    path("draft/", views.draft, name="draft"),
]
