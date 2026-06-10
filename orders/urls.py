from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrderViewSet, IncidentViewSet

router = DefaultRouter()
router.register(r'incidents', IncidentViewSet, basename='incident')
router.register(r'', OrderViewSet, basename='order')


urlpatterns = [
    path('', include(router.urls)),
]
