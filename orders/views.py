from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Order, OrderItem, OrderHistory
from .serializers import OrderSerializer, OrderItemSerializer

class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = {
        'user_id': ['exact'],
        'status': ['exact'],
        'created_at': ['gte', 'lte'],
    }
    ordering_fields = ['created_at', 'total_amount']

    def perform_create(self, serializer):
        from django.utils import timezone
        from datetime import timedelta
        import threading
        import requests
        import os

        # Establecer fecha de entrega estimada (3 días después)
        estimated_delivery = timezone.now() + timedelta(days=3)
        order = serializer.save(estimated_delivery_date=estimated_delivery)
        
        # Registrar historial inicial
        OrderHistory.objects.create(order=order, status=order.status, comment="Pedido creado")

        # Simular evento asincrónico para descontar inventario
        def reduce_catalog_stock():
            catalog_url = os.getenv('CATALOG_SERVICE_URL', 'http://localhost:8002/api/products/bulk_reduce_stock/')
            items_data = [
                {"product_id": item.product_id, "quantity": item.quantity}
                for item in order.items.all()
            ]
            try:
                requests.post(catalog_url, json={"items": items_data}, timeout=5)
            except Exception as e:
                print(f"Error notifying catalog service: {e}")

        # Ejecutar en segundo plano (simulando asincronía)
        thread = threading.Thread(target=reduce_catalog_stock)
        thread.start()

    @action(detail=True, methods=['patch'])
    def update_status(self, request, pk=None):
        order = self.get_object()
        new_status = request.data.get('status')
        comment = request.data.get('comment', '')

        if new_status not in dict(Order.STATUS_CHOICES):
            return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)

        order.status = new_status
        order.save()
        
        OrderHistory.objects.create(order=order, status=new_status, comment=comment)
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=['patch'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        
        if order.status in ['ENVIADO', 'ENTREGADO', 'CANCELADO']:
            return Response({"error": f"Cannot cancel order in status {order.status}"}, status=status.HTTP_400_BAD_REQUEST)

        order.status = 'CANCELADO'
        order.save()
        
        OrderHistory.objects.create(order=order, status='CANCELADO', comment="Cancelado por el usuario")
        return Response(OrderSerializer(order).data)
