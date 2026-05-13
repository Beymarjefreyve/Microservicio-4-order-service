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
        import pika
        import json
        import requests
        import os
        from rest_framework.exceptions import ValidationError

        estimated_delivery = timezone.now() + timedelta(days=3)
        order = serializer.save(estimated_delivery_date=estimated_delivery)
        
        OrderHistory.objects.create(order=order, status=order.status, comment="Pedido creado")

        def publish_order_created():
            try:
                rabbitmq_host = os.getenv('RABBITMQ_HOST', '127.0.0.1')
                connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbitmq_host))
                channel = connection.channel()
                channel.queue_declare(queue='order_queue', durable=True)
                
                message = {
                    "event": "order_created",
                    "order_id": order.id,
                    "items": [{"product_id": i.product_id, "quantity": i.quantity} for i in order.items.all()]
                }
                
                channel.basic_publish(
                    exchange='',
                    routing_key='order_queue',
                    body=json.dumps(message),
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                connection.close()
            except Exception as e:
                print(f"Error publishing to RabbitMQ: {e}")

        publish_order_created()

    @action(detail=True, methods=['patch'])
    def update_status(self, request, pk=None):
        order = self.get_object()
        new_status = request.data.get('status')
        comment = request.data.get('comment', '')
        payment_method = request.data.get('payment_method')

        if new_status not in dict(Order.STATUS_CHOICES):
            return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)

        order.status = new_status
        if payment_method:
            order.payment_method = payment_method
        order.save()
        
        OrderHistory.objects.create(order=order, status=new_status, comment=comment)
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=['patch'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        
        if order.status in ['ENVIADO', 'ENTREGADO', 'CANCELADO']:
            return Response({"error": f"No se puede cancelar en estado {order.status}"}, status=status.HTTP_400_BAD_REQUEST)

        order.status = 'CANCELADO'
        order.save()
        
        OrderHistory.objects.create(order=order, status='CANCELADO', comment="Cancelado por el usuario")

        # Restaurar stock vía Catalog Service para consistencia total
        import os
        import requests
        catalog_url = os.getenv('CATALOG_SERVICE_URL', 'http://127.0.0.1:8002/api/products')
        restore_items = [{"product_id": i.product_id, "quantity": i.quantity} for i in order.items.all()]
        
        if restore_items:
            try:
                requests.post(f"{catalog_url}/bulk_restore_stock/", json={"items": restore_items}, timeout=10)
            except Exception as e:
                print(f"Error restoring stock via catalog: {e}")

        return Response(OrderSerializer(order).data)
