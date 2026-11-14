from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("druzyna/", views.team, name="team"),
    path("druzyna/<int:player_id>/", views.team, name="team_of"),
    path("weekendy/", views.weekends, name="weekends"),
    path("weekendy/<int:pk>/", views.weekend_detail, name="weekend_detail"),
    path("draft/", views.draft, name="draft"),
    path("transfery/", views.transfers, name="transfers"),
    path("transfery/<int:weekend_id>/", views.transfers, name="transfers_for"),
    path("transfery/<int:weekend_id>/otworz/", views.transfer_open, name="transfer_open"),
    path("transfery/<int:weekend_id>/wykonaj/", views.transfer_make, name="transfer_make"),
    path("transfery/<int:weekend_id>/pomin/", views.transfer_skip, name="transfer_skip"),
]
