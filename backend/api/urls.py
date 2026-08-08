from django.urls import path
from . import views

urlpatterns = [
    path("recommendations/", views.recommendations, name="recommendations"),
    path("search/", views.search, name="search"),
    path("recording/", views.recording, name="recording"),
    path("random/", views.random_tracks, name="random"),
    path("coverart/", views.coverart, name="coverart"),
]
