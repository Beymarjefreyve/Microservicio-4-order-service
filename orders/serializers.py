from rest_framework import serializers
from .models import Order, OrderItem, OrderHistory

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['id', 'product_id', 'product_name', 'quantity', 'price_at_purchase']

class OrderHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderHistory
        fields = ['id', 'status', 'changed_at', 'comment']

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, required=False)
    history = OrderHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ['id', 'user_id', 'user_name', 'user_email', 'status', 'total_amount', 'tax_amount', 'shipping_address', 'payment_method', 'items', 'history', 'estimated_delivery_date', 'created_at', 'updated_at']

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        order = Order.objects.create(**validated_data)
        for item_data in items_data:
            OrderItem.objects.create(order=order, **item_data)
        return order
