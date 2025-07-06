from django.db import models
from marketplace.models import Product

class Stock(models.Model):
    product = models.ForeignKey('marketplace.Product', on_delete=models.CASCADE, related_name='stock_records')
    quantity = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.product.name} - {self.quantity} in stock"
