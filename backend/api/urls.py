from django.urls import path
from . import views

urlpatterns = [
    path("recommendations/", views.recommendations, name="recommendations"),
    path("search/", views.search, name="search"),
    path("tracks/", views.tracks, name="tracks"),
]
