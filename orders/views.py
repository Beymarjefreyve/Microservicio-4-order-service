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

        # Validar stock sincrónicamente (P3)
        # Validar stock sincrónicamente con el servicio de inventario
        inventory_url = os.getenv('INVENTORY_SERVICE_URL', 'http://localhost:8003/api/inventory')
        items_data = serializer.validated_data.get('items', [])
        for item in items_data:
            try:
                inv_resp = requests.get(f"{inventory_url}/{item['product_id']}/", timeout=5)
                if inv_resp.status_code == 200:
                    inventory_data = inv_resp.json()
                    if inventory_data.get('quantity', 0) < item['quantity']:
                        raise ValidationError(f"Stock insuficiente para el producto ID {item['product_id']}")
                else:
                    raise ValidationError(f"No se pudo verificar el stock para el producto {item['product_id']}")
            except requests.exceptions.RequestException:
                raise ValidationError("Error al comunicar con el servicio de inventario.")

        # Establecer fecha de entrega estimada
        estimated_delivery = timezone.now() + timedelta(days=3)
        order = serializer.save(estimated_delivery_date=estimated_delivery)
        
        # Registrar historial inicial
        OrderHistory.objects.create(order=order, status=order.status, comment="Pedido creado")

        # Publicar evento en RabbitMQ
        def publish_order_created():
            try:
                connection = pika.BlockingConnection(pika.ConnectionParameters(host=os.getenv('RABBITMQ_HOST', 'localhost')))
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
                    properties=pika.BasicProperties(delivery_mode=2) # make message persistent
                )
                connection.close()
            except Exception as e:
                print(f"Error publishing to RabbitMQ: {e}")

        # Ejecutar publicador
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
            return Response({"error": f"Cannot cancel order in status {order.status}"}, status=status.HTTP_400_BAD_REQUEST)

        order.status = 'CANCELADO'
        order.save()
        
        OrderHistory.objects.create(order=order, status='CANCELADO', comment="Cancelado por el usuario")

        # Restaurar stock (P1)
        import pika
        import json
        import os
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=os.getenv('RABBITMQ_HOST', 'localhost')))
            channel = connection.channel()
            channel.queue_declare(queue='order_queue', durable=True)
            
            message = {
                "event": "order_cancelled",
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
            print(f"Error publishing cancel event to RabbitMQ: {e}")

        return Response(OrderSerializer(order).data)
