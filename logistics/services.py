"""
Logistics Services Module

This module contains business logic services for the logistics application.
Services encapsulate complex business operations and provide clean interfaces
for views and other components.

Author: Logistics Team
Version: 2.0.0
"""

from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from datetime import datetime, timedelta
import logging

from django.db import transaction
from django.db.models import Q, Count, Avg, Sum, F
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import (
    Shipment, ShipmentBox, BoxItem, Driver, Vehicle,
    Warehouse, LogisticOffice
)
from orders.models import Order, OrderItem
from .utils import (
    calculate_distance_haversine,
    geocode_address,
    validate_plus_code,
    decode_plus_code
)

logger = logging.getLogger(__name__)


# ============================================================================
# NOTIFICATION SERVICE
# ============================================================================

class NotificationService:
    """
    Service for handling all notification operations.
    Abstracts the complexity of multi-channel notifications.
    """

    @staticmethod
    def send_shipment_created_notification(shipment: Shipment) -> None:
        """Send notifications when a new shipment is created."""
        from marketplace.notifications import send_email, send_whatsapp

        # Notify driver
        if shipment.driver:
            message = (
                f"New shipment assigned: {shipment.tracking_number}\n"
                f"Pickup: {shipment.warehouse.name if shipment.warehouse else 'TBD'}\n"
                f"Delivery: {shipment.shipping_address.city}"
            )
            try:
                send_email("New Shipment Assignment", message, [shipment.driver.user.email])
                send_whatsapp(shipment.driver.phone, message)
            except Exception as e:
                logger.error(f"Failed to notify driver: {str(e)}")

        # Notify customer
        if shipment.order and shipment.order.buyer:
            buyer = shipment.order.buyer
            message = (
                f"Your order #{shipment.order.id} is being prepared for shipment.\n"
                f"Tracking: {shipment.tracking_number}"
            )
            try:
                send_email("Order Processing", message, [buyer.email])
                if buyer.telephone:
                    send_whatsapp(buyer.telephone, message)
            except Exception as e:
                logger.error(f"Failed to notify customer: {str(e)}")

    @staticmethod
    def send_status_change_notification(shipment: Shipment, old_status: str) -> None:
        """Send notifications when shipment status changes."""
        from marketplace.notifications import send_email, send_whatsapp

        if not shipment.order or not shipment.order.buyer:
            return

        buyer = shipment.order.buyer
        status_messages = {
            'shipped': "Your order has been shipped and is ready for pickup by our driver.",
            'in_transit': "Your order is on the way! The driver is en route to your location.",
            'delivered': "Your order has been delivered successfully. Thank you for your business!",
        }

        message = status_messages.get(shipment.status)
        if message:
            try:
                subject = f"Order #{shipment.order.id} - {shipment.get_status_display()}"
                full_message = f"{message}\n\nTracking: {shipment.tracking_number}"
                send_email(subject, full_message, [buyer.email])
                if buyer.telephone:
                    send_whatsapp(buyer.telephone, full_message)
            except Exception as e:
                logger.error(f"Failed to send status notification: {str(e)}")


# ============================================================================
# SHIPMENT SERVICE
# ============================================================================

class ShipmentService:
    """
    Service for managing shipment operations and business logic.
    """

    @staticmethod
    @transaction.atomic
    def create_shipment_with_boxes(
            shipment_data: Dict[str, Any],
            boxes_data: List[Dict[str, Any]]
    ) -> Shipment:
        """
        Create a shipment with multiple boxes in a single transaction.

        Args:
            shipment_data: Dictionary containing shipment field values
            boxes_data: List of dictionaries containing box data

        Returns:
            Created Shipment instance

        Raises:
            ValidationError: If data is invalid
        """
        # Create shipment
        shipment = Shipment.objects.create(**shipment_data)

        # Create boxes
        for box_data in boxes_data:
            box = ShipmentBox.objects.create(
                shipment=shipment,
                **box_data
            )

            # Generate QR label
            box.generate_qr_label()

        logger.info(f"Created shipment {shipment.tracking_number} with {len(boxes_data)} boxes")

        return shipment

    @staticmethod
    def calculate_shipment_metrics(shipment: Shipment) -> Dict[str, Any]:
        """
        Calculate various metrics for a shipment.

        Args:
            shipment: Shipment instance

        Returns:
            Dictionary containing calculated metrics
        """
        metrics = {
            'total_boxes': shipment.boxes.count(),
            'total_weight': sum(box.weight_kg or 0 for box in shipment.boxes.all()),
            'total_items': 0,
        }

        # Calculate total items
        for box in shipment.boxes.all():
            metrics['total_items'] += box.get_total_items_count()

        # Calculate delivery time if delivered
        if shipment.status == 'delivered' and shipment.actual_dropoff_time:
            time_diff = shipment.actual_dropoff_time - shipment.collect_time
            metrics['delivery_time_hours'] = time_diff.total_seconds() / 3600
            metrics['was_on_time'] = shipment.actual_dropoff_time <= shipment.estimated_dropoff_time

        return metrics

    @staticmethod
    def validate_shipment_capacity(shipment: Shipment) -> Tuple[bool, Optional[str]]:
        """
        Validate that assigned vehicle has sufficient capacity.

        Args:
            shipment: Shipment instance

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not shipment.vehicle:
            return True, None

        vehicle = shipment.vehicle

        # Check weight capacity
        if shipment.weight_kg > vehicle.capacity_kg:
            return False, f"Shipment weight ({shipment.weight_kg}kg) exceeds vehicle capacity ({vehicle.capacity_kg}kg)"

        # Check volume capacity
        if vehicle.capacity_cubic_meters and shipment.size_cubic_meters > vehicle.capacity_cubic_meters:
            return False, f"Shipment volume ({shipment.size_cubic_meters}m³) exceeds vehicle capacity ({vehicle.capacity_cubic_meters}m³)"

        return True, None

    @staticmethod
    def auto_assign_driver_and_vehicle(
            shipment: Shipment,
            warehouse: Optional[Warehouse] = None
    ) -> Tuple[Optional[Driver], Optional[Vehicle]]:
        """
        Automatically assign the best available driver and vehicle to a shipment.

        Args:
            shipment: Shipment to assign resources to
            warehouse: Optional warehouse to prioritize proximity

        Returns:
            Tuple of (assigned_driver, assigned_vehicle)
        """
        # Get available drivers (active with valid license)
        available_drivers = Driver.objects.filter(
            is_active=True,
        ).annotate(
            active_shipments=Count(
                'shipments',
                filter=Q(shipments__status__in=['pending', 'in_transit', 'shipped'])
            )
        ).filter(
            active_shipments__lt=5  # Not overloaded
        ).order_by('active_shipments')

        # Filter drivers with valid license
        available_drivers = [d for d in available_drivers if d.is_license_valid()]

        if not available_drivers:
            logger.warning("No available drivers found for auto-assignment")
            return None, None

        # Get best driver (least loaded)
        best_driver = available_drivers[0]

        # Find suitable vehicle for this driver
        suitable_vehicle = Vehicle.objects.filter(
            driver=best_driver,
            is_active=True,
            capacity_kg__gte=shipment.weight_kg
        ).first()

        if not suitable_vehicle:
            # Try to find any available vehicle with sufficient capacity
            suitable_vehicle = Vehicle.objects.filter(
                is_active=True,
                capacity_kg__gte=shipment.weight_kg,
                driver__isnull=True
            ).first()

        logger.info(
            f"Auto-assigned driver {best_driver.employee_id} "
            f"and vehicle {suitable_vehicle.plate_number if suitable_vehicle else 'None'} "
            f"to shipment {shipment.tracking_number}"
        )

        return best_driver, suitable_vehicle


# ============================================================================
# ANALYTICS SERVICE
# ============================================================================

class AnalyticsService:
    """
    Service for generating analytics and reports.
    """

    @staticmethod
    def get_delivery_performance_metrics(
            start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Calculate delivery performance metrics for a date range.

        Args:
            start_date: Start of date range (default: 30 days ago)
            end_date: End of date range (default: now)

        Returns:
            Dictionary containing performance metrics
        """
        if not start_date:
            start_date = timezone.now() - timedelta(days=30)
        if not end_date:
            end_date = timezone.now()

        # Get shipments in date range
        shipments = Shipment.objects.filter(
            created_at__range=(start_date, end_date)
        )

        total_shipments = shipments.count()
        delivered_shipments = shipments.filter(status='delivered')

        # Calculate on-time delivery rate
        on_time = delivered_shipments.filter(
            actual_dropoff_time__lte=F('estimated_dropoff_time')
        ).count()

        on_time_rate = (on_time / delivered_shipments.count() * 100) if delivered_shipments.count() > 0 else 0

        # Calculate average delivery time
        avg_delivery_time = None
        delivered_with_times = delivered_shipments.filter(
            actual_dropoff_time__isnull=False
        )

        if delivered_with_times.exists():
            total_seconds = sum(
                (s.actual_dropoff_time - s.collect_time).total_seconds()
                for s in delivered_with_times
            )
            avg_delivery_time = total_seconds / delivered_with_times.count() / 3600  # Convert to hours

        # Status distribution
        status_distribution = dict(
            shipments.values_list('status').annotate(count=Count('id'))
        )

        return {
            'total_shipments': total_shipments,
            'delivered_shipments': delivered_shipments.count(),
            'on_time_rate': round(on_time_rate, 2),
            'average_delivery_time_hours': round(avg_delivery_time, 2) if avg_delivery_time else None,
            'status_distribution': status_distribution,
            'pending_shipments': shipments.filter(status='pending').count(),
            'in_transit_shipments': shipments.filter(status='in_transit').count(),
            'cancelled_shipments': shipments.filter(status='cancelled').count(),
        }

    @staticmethod
    def get_driver_performance(
            driver: Driver,
            start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Calculate performance metrics for a specific driver.

        Args:
            driver: Driver instance
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dictionary containing driver performance metrics
        """
        if not start_date:
            start_date = timezone.now() - timedelta(days=30)
        if not end_date:
            end_date = timezone.now()

        shipments = driver.shipments.filter(
            created_at__range=(start_date, end_date)
        )

        total_deliveries = shipments.filter(status='delivered').count()

        # On-time deliveries
        on_time = shipments.filter(
            status='delivered',
            actual_dropoff_time__lte=F('estimated_dropoff_time')
        ).count()

        on_time_rate = (on_time / total_deliveries * 100) if total_deliveries > 0 else 0

        # Average rating (if ratings model exists)
        # avg_rating = driver.ratings.aggregate(avg=Avg('score'))['avg']

        return {
            'driver_name': driver.user.get_full_name(),
            'employee_id': driver.employee_id,
            'total_shipments': shipments.count(),
            'total_deliveries': total_deliveries,
            'on_time_deliveries': on_time,
            'on_time_rate': round(on_time_rate, 2),
            'active_shipments': shipments.filter(
                status__in=['pending', 'in_transit', 'shipped']
            ).count(),
            'cancelled_shipments': shipments.filter(status='cancelled').count(),
            # 'average_rating': round(avg_rating, 2) if avg_rating else None,
        }

    @staticmethod
    def get_warehouse_utilization_report(
            warehouse: Optional[Warehouse] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate warehouse utilization report.

        Args:
            warehouse: Optional specific warehouse (default: all)

        Returns:
            List of warehouse utilization data
        """
        warehouses = [warehouse] if warehouse else Warehouse.objects.filter(is_active=True)

        report = []
        for wh in warehouses:
            # Count active shipments
            active_shipments = wh.shipments.filter(
                status__in=['pending', 'in_transit']
            )

            # Calculate volume utilization
            total_volume = active_shipments.aggregate(
                total=Sum('size_cubic_meters')
            )['total'] or 0

            utilization_rate = 0
            if wh.capacity_cubic_meters:
                utilization_rate = (total_volume / float(wh.capacity_cubic_meters)) * 100

            report.append({
                'warehouse_id': wh.id,
                'warehouse_name': wh.name,
                'warehouse_code': wh.code,
                'capacity_cubic_meters': float(wh.capacity_cubic_meters) if wh.capacity_cubic_meters else None,
                'current_volume': float(total_volume),
                'utilization_rate': round(utilization_rate, 2),
                'active_shipments': active_shipments.count(),
                'is_near_capacity': utilization_rate > 80,
            })

        return report

    @staticmethod
    def get_vehicle_utilization_metrics() -> Dict[str, Any]:
        """
        Calculate fleet utilization metrics.

        Returns:
            Dictionary containing vehicle utilization data
        """
        total_vehicles = Vehicle.objects.filter(is_active=True).count()

        # Vehicles with active shipments
        vehicles_in_use = Vehicle.objects.filter(
            is_active=True,
            shipments__status__in=['in_transit', 'shipped']
        ).distinct().count()

        # Vehicles needing maintenance
        vehicles_need_maintenance = Vehicle.objects.filter(
            is_active=True,
            next_maintenance__lte=timezone.now().date()
        ).count()

        utilization_rate = (vehicles_in_use / total_vehicles * 100) if total_vehicles > 0 else 0

        return {
            'total_vehicles': total_vehicles,
            'vehicles_in_use': vehicles_in_use,
            'vehicles_available': total_vehicles - vehicles_in_use,
            'utilization_rate': round(utilization_rate, 2),
            'vehicles_need_maintenance': vehicles_need_maintenance,
        }


# ============================================================================
# ROUTE OPTIMIZATION SERVICE
# ============================================================================

class RouteOptimizationService:
    """
    Service for route optimization and distance calculations.
    In production, this would integrate with mapping APIs like Google Maps or Mapbox.
    """

    @staticmethod
    def calculate_distance(
            origin_lat: float,
            origin_lng: float,
            dest_lat: float,
            dest_lng: float
    ) -> float:
        """
        Calculate distance between two coordinates (Haversine formula).

        Args:
            origin_lat: Origin latitude
            origin_lng: Origin longitude
            dest_lat: Destination latitude
            dest_lng: Destination longitude

        Returns:
            Distance in kilometers
        """
        from math import radians, sin, cos, sqrt, atan2

        # Earth radius in kilometers
        R = 6371.0

        lat1 = radians(origin_lat)
        lon1 = radians(origin_lng)
        lat2 = radians(dest_lat)
        lon2 = radians(dest_lng)

        dlon = lon2 - lon1
        dlat = lat2 - lat1

        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))

        distance = R * c
        return round(distance, 2)

    @staticmethod
    def estimate_delivery_time(
            distance_km: float,
            shipment_type: str = 'normal'
    ) -> timedelta:
        """
        Estimate delivery time based on distance and shipment type.

        Args:
            distance_km: Distance in kilometers
            shipment_type: Type of shipment (affects speed)

        Returns:
            Estimated delivery time as timedelta
        """
        # Average speeds by shipment type (km/h)
        speeds = {
            'express': 60,
            'same_day': 50,
            'normal': 40,
            'economic': 30,
        }

        speed = speeds.get(shipment_type, 40)
        hours = distance_km / speed

        # Add buffer time (20% for traffic, stops, etc.)
        hours *= 1.2

        return timedelta(hours=hours)

    @staticmethod
    def optimize_route(shipments: List[Shipment]) -> List[Shipment]:
        """
        Optimize delivery route for multiple shipments.
        Uses nearest neighbor algorithm (simple implementation).
        In production, use proper optimization algorithms or APIs.

        Args:
            shipments: List of shipments to optimize

        Returns:
            Optimized list of shipments
        """
        if len(shipments) <= 1:
            return shipments

        # This is a placeholder - implement proper route optimization
        # using algorithms like:
        # - Nearest Neighbor
        # - Genetic Algorithms
        # - Google OR-Tools
        # - External routing APIs

        return sorted(shipments, key=lambda s: s.estimated_dropoff_time)


# ============================================================================
# PRICING SERVICE
# ============================================================================

class PricingService:
    """
    Service for calculating shipping costs and pricing.
    """

    BASE_RATES = {
        'express': Decimal('15.00'),
        'same_day': Decimal('25.00'),
        'normal': Decimal('10.00'),
        'economic': Decimal('5.00'),
        'free': Decimal('0.00'),
    }

    WEIGHT_RATE_PER_KG = Decimal('0.50')
    VOLUME_RATE_PER_CUBIC_METER = Decimal('10.00')
    DISTANCE_RATE_PER_KM = Decimal('0.30')

    @classmethod
    def calculate_shipping_cost(
            cls,
            shipment_type: str,
            weight_kg: Decimal,
            volume_cubic_meters: Decimal,
            distance_km: Optional[float] = None
    ) -> Decimal:
        """
        Calculate shipping cost based on various factors.

        Args:
            shipment_type: Type of shipment
            weight_kg: Weight in kilograms
            volume_cubic_meters: Volume in cubic meters
            distance_km: Optional distance in kilometers

        Returns:
            Calculated shipping cost
        """
        # Base rate
        cost = cls.BASE_RATES.get(shipment_type, cls.BASE_RATES['normal'])

        # Weight charge
        cost += weight_kg * cls.WEIGHT_RATE_PER_KG

        # Volume charge
        cost += volume_cubic_meters * cls.VOLUME_RATE_PER_CUBIC_METER

        # Distance charge
        if distance_km:
            cost += Decimal(str(distance_km)) * cls.DISTANCE_RATE_PER_KM

        return cost.quantize(Decimal('0.01'))


# ============================================================================
# EXPORT SERVICE
# ============================================================================

class ExportService:
    """
    Service for exporting data in various formats.
    """

    @staticmethod
    def export_shipments_to_csv(queryset) -> str:
        """
        Export shipments to CSV format.

        Args:
            queryset: Shipment queryset

        Returns:
            CSV string
        """
        import csv
        from io import StringIO

        output = StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            'Tracking Number', 'Status', 'Weight (kg)', 'Volume (m³)',
            'Driver', 'Vehicle', 'Warehouse', 'Created At', 'Estimated Delivery'
        ])

        # Write data
        for shipment in queryset:
            writer.writerow([
                shipment.tracking_number,
                shipment.get_status_display(),
                shipment.weight_kg,
                shipment.size_cubic_meters,
                shipment.driver.user.get_full_name() if shipment.driver else 'Unassigned',
                shipment.vehicle.plate_number if shipment.vehicle else 'Unassigned',
                shipment.warehouse.name if shipment.warehouse else 'N/A',
                shipment.created_at.strftime('%Y-%m-%d %H:%M'),
                shipment.estimated_dropoff_time.strftime('%Y-%m-%d %H:%M'),
            ])

        return output.getvalue()


class LocationService:
    """
    Service for handling shipment location data and geocoding operations.
    Provides comprehensive location information for tracking and navigation.
    """

    @staticmethod
    def get_shipment_location_data(shipment: Shipment) -> Dict[str, Any]:
        """
        Get comprehensive location data for a shipment including coordinates,
        address information, Plus Codes, and map URLs.

        Args:
            shipment: Shipment instance

        Returns:
            Dictionary containing all location-related information

        Example:
            {
                'shipment_id': 123,
                'tracking_number': 'TRK123',
                'customer_name': 'John Doe',
                'phone': '+1234567890',
                'address': {
                    'street': '123 Main St',
                    'city': 'Springfield',
                    'region': 'State',
                    'country': 'USA',
                    'postal_code': '12345',
                    'geo_code': '9G8F+GH',
                    'full_address': '123 Main St, Springfield, State'
                },
                'coordinates': {
                    'lat': 37.7749,
                    'lng': -122.4194,
                    'source': 'plus_code',  # or 'geocoded' or 'manual'
                    'accuracy': 'high'  # or 'medium' or 'low'
                },
                'plus_code': {
                    'code': '9G8F+GH',
                    'is_valid': True,
                    'decoded_lat': 37.7749,
                    'decoded_lng': -122.4194
                },
                'maps_urls': {
                    'directions': 'https://www.google.com/maps/dir/?api=1&destination=...',
                    'view': 'https://www.google.com/maps?q=...',
                    'plus_code_url': 'https://plus.codes/9G8F+GH'
                },
                'shipment_details': {
                    'weight_kg': 25.5,
                    'size_cubic_meters': 0.5,
                    'material_type': 'General',
                    'shipment_type': 'Standard',
                    'status': 'in_transit',
                    'estimated_delivery': '2026-01-02T16:00:00Z',
                    'boxes_count': 3
                },
                'warehouse_info': {
                    'name': 'Main Warehouse',
                    'address': 'Warehouse St 1',
                    'coordinates': {'lat': 37.7, 'lng': -122.4}
                } if warehouse else None
            }
        """

        # Get shipping address
        address = shipment.shipping_address
        if not address:
            return {
                'error': 'No shipping address available',
                'shipment_id': shipment.id
            }

        # Build basic address information
        address_data = {
            'street': address.address,
            'city': address.city,
            'region': address.region,
            'country': address.country,
            'postal_code': address.postal_code if hasattr(address, 'postal_code') else '',
            'geo_code': address.geo_code if hasattr(address, 'geo_code') else '',
            'full_address': f"{address.address}, {address.city}, {address.region}"
        }

        # Initialize coordinates
        coordinates = None
        coordinates_source = None
        accuracy = 'low'

        # Try to get coordinates from Plus Code first (highest accuracy)
        plus_code_data = None
        if address_data['geo_code']:
            is_valid = validate_plus_code(address_data['geo_code'])
            if is_valid:
                decoded = decode_plus_code(address_data['geo_code'])
                if decoded and 'lat' in decoded and 'lng' in decoded:
                    coordinates = {
                        'lat': float(decoded['lat']),
                        'lng': float(decoded['lng'])
                    }
                    coordinates_source = 'plus_code'
                    accuracy = 'high'

                    plus_code_data = {
                        'code': address_data['geo_code'],
                        'is_valid': True,
                        'decoded_lat': coordinates['lat'],
                        'decoded_lng': coordinates['lng']
                    }

        # If no Plus Code, try manual coordinates from address model
        if not coordinates:
            if hasattr(address, 'latitude') and hasattr(address, 'longitude'):
                if address.latitude and address.longitude:
                    coordinates = {
                        'lat': float(address.latitude),
                        'lng': float(address.longitude)
                    }
                    coordinates_source = 'manual'
                    accuracy = 'medium'

        # If still no coordinates, try geocoding the address
        if not coordinates:
            geocoded = geocode_address(address_data['full_address'])
            if geocoded and 'lat' in geocoded and 'lng' in geocoded:
                coordinates = {
                    'lat': float(geocoded['lat']),
                    'lng': float(geocoded['lng'])
                }
                coordinates_source = 'geocoded'
                accuracy = geocoded.get('accuracy', 'low')

        # Build map URLs
        maps_urls = {}
        if coordinates:
            lat_lng = f"{coordinates['lat']},{coordinates['lng']}"

            # Google Maps Directions URL
            maps_urls['directions'] = (
                f"https://www.google.com/maps/dir/?api=1&destination={lat_lng}"
            )

            # Google Maps View URL
            maps_urls['view'] = f"https://www.google.com/maps?q={lat_lng}"

            # Plus Code URL (if available)
            if plus_code_data:
                maps_urls['plus_code_url'] = (
                    f"https://plus.codes/{plus_code_data['code']}"
                )

        # Get customer information
        customer_name = "Unknown"
        customer_phone = ""

        if shipment.order and shipment.order.buyer:
            customer_name = shipment.order.buyer.get_full_name() or shipment.order.buyer.username
            if hasattr(shipment.order.buyer, 'phone'):
                customer_phone = shipment.order.buyer.phone

        # If phone in address
        if hasattr(address, 'phone') and address.phone:
            customer_phone = address.phone

        # Build shipment details
        shipment_details = {
            'weight_kg': float(shipment.weight_kg),
            'size_cubic_meters': float(shipment.size_cubic_meters),
            'material_type': shipment.get_material_type_display(),
            'shipment_type': shipment.get_shipment_type_display(),
            'status': shipment.status,
            'status_display': shipment.get_status_display(),
            'estimated_delivery': shipment.estimated_dropoff_time.isoformat() if shipment.estimated_dropoff_time else None,
            'boxes_count': shipment.boxes.count() if hasattr(shipment, 'boxes') else 0
        }

        # Get warehouse information
        warehouse_info = None
        if shipment.warehouse:
            warehouse = shipment.warehouse
            warehouse_coords = None

            if hasattr(warehouse, 'latitude') and hasattr(warehouse, 'longitude'):
                if warehouse.latitude and warehouse.longitude:
                    warehouse_coords = {
                        'lat': float(warehouse.latitude),
                        'lng': float(warehouse.longitude)
                    }

            warehouse_info = {
                'name': warehouse.name,
                'code': warehouse.code if hasattr(warehouse, 'code') else '',
                'address': warehouse.address,
                'coordinates': warehouse_coords
            }

        # Build complete response
        return {
            'shipment_id': shipment.id,
            'tracking_number': shipment.tracking_number or f"#{shipment.id}",
            'customer_name': customer_name,
            'phone': customer_phone,
            'address': address_data,
            'coordinates': coordinates,
            'coordinates_source': coordinates_source,
            'accuracy': accuracy,
            'plus_code': plus_code_data,
            'maps_urls': maps_urls,
            'shipment_details': shipment_details,
            'warehouse_info': warehouse_info
        }

    @staticmethod
    def calculate_route_distance(origin_coords: Dict, destination_coords: Dict) -> Optional[float]:
        """
        Calculate distance between two coordinates using Haversine formula.

        Args:
            origin_coords: {'lat': float, 'lng': float}
            destination_coords: {'lat': float, 'lng': float}

        Returns:
            Distance in kilometers, or None if calculation fails
        """
        try:
            return calculate_distance_haversine(
                origin_coords['lat'],
                origin_coords['lng'],
                destination_coords['lat'],
                destination_coords['lng']
            )
        except Exception as e:
            return None

    @staticmethod
    def get_estimated_delivery_time(distance_km: float, avg_speed_kmh: float = 30) -> int:
        """
        Estimate delivery time based on distance and average speed.

        Args:
            distance_km: Distance in kilometers
            avg_speed_kmh: Average speed in km/h (default 30 for urban)

        Returns:
            Estimated time in minutes
        """
        if distance_km <= 0 or avg_speed_kmh <= 0:
            return 0

        hours = distance_km / avg_speed_kmh
        minutes = int(hours * 60)

        # Add buffer time for traffic, stops, etc.
        buffer_minutes = int(minutes * 0.2)  # 20% buffer

        return minutes + buffer_minutes

    @staticmethod
    def get_nearby_landmarks(coordinates: Dict[str, float], radius_km: float = 1.0) -> List[str]:
        """
        Get nearby landmarks for better navigation (placeholder).
        In production, this would integrate with Google Places API or similar.

        Args:
            coordinates: {'lat': float, 'lng': float}
            radius_km: Search radius in kilometers

        Returns:
            List of landmark descriptions
        """
        # This is a placeholder. In production, you would:
        # 1. Call Google Places API
        # 2. Filter for prominent landmarks
        # 3. Return formatted descriptions

        return [
            "Near major intersection",
            "Residential area",
            "Main road access"
        ]

    @staticmethod
    def validate_delivery_location(shipment: Shipment) -> Dict[str, Any]:
        """
        Validate if delivery location has sufficient information for navigation.

        Args:
            shipment: Shipment instance

        Returns:
            Validation result with warnings/errors
        """
        location_data = LocationService.get_shipment_location_data(shipment)

        issues = []
        warnings = []

        # Check for coordinates
        if not location_data.get('coordinates'):
            issues.append("No coordinates available - navigation may be difficult")

        # Check coordinate accuracy
        accuracy = location_data.get('accuracy', 'low')
        if accuracy == 'low':
            warnings.append("Location accuracy is low - verify address with customer")

        # Check for phone number
        if not location_data.get('phone'):
            warnings.append("No phone number - may be difficult to contact customer")

        # Check for Plus Code
        if not location_data.get('plus_code'):
            warnings.append("No Plus Code - consider adding for better accuracy")

        return {
            'is_valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'location_data': location_data
        }


class DeliveryInstructionsService:
    """
    Service for generating and enhancing delivery instructions.
    Provides context-aware instructions based on location, shipment type, and conditions.
    """

    @staticmethod
    def generate_basic_instructions(shipment: Shipment) -> List[str]:
        """
        Generate basic delivery instructions based on shipment properties.

        Args:
            shipment: Shipment instance

        Returns:
            List of instruction strings
        """
        instructions = []

        # Weight-based instructions
        if shipment.weight_kg > 50:
            instructions.append("⚠️ HEAVY ITEM - Use proper lifting techniques or request assistance")
        elif shipment.weight_kg > 20:
            instructions.append("⚠️ Moderate weight - Handle with care")

        # Size-based instructions
        if shipment.size_cubic_meters > 1.0:
            instructions.append("📦 LARGE PACKAGE - May require two-person delivery")

        # Material type instructions
        material_instructions = {
            'fragile': "🔴 FRAGILE - Handle with extreme care, avoid drops or impacts",
            'liquid': "💧 LIQUID CONTENTS - Keep upright at all times",
            'electronic': "⚡ ELECTRONICS - Avoid moisture and extreme temperatures",
            'perishable': "❄️ PERISHABLE - Deliver as soon as possible, maintain cool temperature",
            'hazardous': "☢️ HAZARDOUS MATERIAL - Follow safety protocols"
        }

        if shipment.material_type in material_instructions:
            instructions.append(material_instructions[shipment.material_type])

        # Number of boxes
        box_count = shipment.boxes.count() if hasattr(shipment, 'boxes') else 0
        if box_count > 1:
            instructions.append(f"📦 MULTIPLE BOXES - Ensure all {box_count} boxes are delivered")

        # Time-sensitive delivery
        if shipment.estimated_dropoff_time:
            now = timezone.now()
            time_until = shipment.estimated_dropoff_time - now

            if time_until.total_seconds() < 3600:  # Less than 1 hour
                instructions.append("🚨 URGENT - Delivery time window less than 1 hour")
            elif time_until.total_seconds() < 7200:  # Less than 2 hours
                instructions.append("⏰ TIME SENSITIVE - Deliver within 2 hours")

        return instructions

    @staticmethod
    def generate_location_instructions(location_data: Dict[str, Any]) -> List[str]:
        """
        Generate location-specific delivery instructions.

        Args:
            location_data: Location data from get_shipment_location_data

        Returns:
            List of location-based instructions
        """
        instructions = []

        # Coordinate accuracy warnings
        accuracy = location_data.get('accuracy', 'low')
        if accuracy == 'low':
            instructions.append("📍 GPS accuracy may be low - verify address with customer before delivery")

        # Plus Code instructions
        if location_data.get('plus_code'):
            plus_code = location_data['plus_code']['code']
            instructions.append(f"➕ Plus Code: {plus_code} - Use for precise navigation")

        # Phone contact
        if location_data.get('phone'):
            instructions.append(f"📞 Customer contact: {location_data['phone']}")
        else:
            instructions.append("⚠️ No phone number available - may be difficult to contact customer")

        # Maps URLs
        if location_data.get('maps_urls'):
            instructions.append("🗺️ Use provided maps URLs for turn-by-turn navigation")

        return instructions

    @staticmethod
    def generate_time_based_instructions(shipment: Shipment) -> List[str]:
        """
        Generate time-specific delivery instructions.

        Args:
            shipment: Shipment instance

        Returns:
            List of time-based instructions
        """
        instructions = []
        now = timezone.now()

        # Time of day considerations
        hour = now.hour

        if 6 <= hour < 9:
            instructions.append("🌅 MORNING DELIVERY - Customers may be preparing for work")
        elif 12 <= hour < 14:
            instructions.append("🍽️ LUNCH TIME - Customer may be unavailable")
        elif 17 <= hour < 20:
            instructions.append("🌆 EVENING DELIVERY - Peak traffic expected")
        elif 20 <= hour or hour < 6:
            instructions.append("🌙 LATE DELIVERY - Verify customer is expecting delivery at this time")

        # Day of week
        weekday = now.weekday()
        if weekday >= 5:  # Saturday or Sunday
            instructions.append("📅 WEEKEND DELIVERY - Confirm customer availability")

        return instructions

    @staticmethod
    def generate_special_instructions(shipment: Shipment) -> List[str]:
        """
        Generate special delivery instructions from order notes or custom fields.

        Args:
            shipment: Shipment instance

        Returns:
            List of special instructions
        """
        instructions = []

        # Check for delivery notes
        if hasattr(shipment, 'delivery_notes') and shipment.delivery_notes:
            instructions.append(f"📝 SPECIAL INSTRUCTIONS: {shipment.delivery_notes}")

        # Check order notes
        if shipment.order and hasattr(shipment.order, 'notes') and shipment.order.notes:
            instructions.append(f"📋 ORDER NOTES: {shipment.order.notes}")

        # Check shipping address notes
        if shipment.shipping_address:
            address = shipment.shipping_address
            if hasattr(address, 'delivery_instructions') and address.delivery_instructions:
                instructions.append(f"🏠 ADDRESS NOTES: {address.delivery_instructions}")

        return instructions


# Add these to your services.py exports
__all__ = [
    'LocationService',
    'DeliveryInstructionsService',
]
