from django.urls import include, path

urlpatterns = [
    path("api/v1/core/", include("apps.core.urls")),
]
