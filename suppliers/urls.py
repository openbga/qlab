from django.urls import path

from . import views

app_name = "suppliers"
urlpatterns = [
    path("", views.supplier_list, name="list"),
    path("new/", views.supplier_new, name="new"),
    path("<int:pk>/", views.supplier_detail, name="detail"),
]
