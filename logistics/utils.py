"""
Logistics Utilities Module

This module provides utility functions for the logistics application,
including geocoding, notifications, validations, and helper functions.

Author: Logistics Team
Version: 2.0.0
"""

from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from datetime import datetime, timedelta
import logging
import requests
from math import radians, sin, cos, sqrt, atan2

from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags
from django.db import transaction
from django.db.models import Count, Q, Avg, F

from .models import Shipment, Driver, Vehicle, Warehouse
from orders.models import Order, OrderStatusHistory

logger = logging.getLogger(__name__)


# ============================================================================
# NOTIFICATION FUNCTIONS
# ============================================================================

def send_delivery_notification(
        shipment: Shipment,
        status: str,
        driver: Optional[Driver] = None,
        use_template: bool = True
) -> bool:
    """
    Send email notification when shipment status changes.

    Args:
        shipment: Shipment instance
        status: New status
        driver: Optional driver instance
        use_template: Whether to use HTML email template

    Returns:
        Boolean indicating success
    """
    if not shipment.order or not shipment.order.buyer or not shipment.order.buyer.email:
        logger.warning(f"Cannot send notification for shipment {shipment.tracking_number}: No recipient")
        return False

    buyer = shipment.order.buyer
    address = shipment.shipping_address

    # Status-specific messages
    status_messages = {
        'pending': 'Your order is being prepared for shipment',
        'shipped': 'Your order has been picked up and is ready for delivery',
        'in_transit': 'Your order is now out for delivery',
        'delivered': 'Your order has been delivered successfully',
        'cancelled': 'Your shipment has been cancelled',
        'returned': 'Your shipment is being returned',
    }

    subject = f"Order Update - Shipment {shipment.tracking_number}"
    status_message = status_messages.get(status, 'Your order status has been updated')

    # Prepare context for template
    context = {
        'buyer_name': buyer.get_full_name() or address.full_name,
        'status_message': status_message,
        'shipment': shipment,
        'order': shipment.order,
        'address': address,
        'driver': driver,
        'tracking_url': f"{settings.SITE_URL}/logistics/track/{shipment.tracking_number}/",
        'status': status,
        'status_display': shipment.get_status_display(),
    }

    try:
        if use_template:
            # Render HTML email from template
            html_message = render_to_string('logistics/emails/delivery_notification.html', context)
            plain_message = strip_tags(html_message)

            email = EmailMultiAlternatives(
                subject=subject,
                body=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[buyer.email]
            )
            email.attach_alternative(html_message, "text/html")
            email.send()
        else:
            # Plain text email
            message = f"""
Dear {context['buyer_name']},

{status_message}.

Shipment Details:
- Tracking Number: {shipment.tracking_number}
- Status: {shipment.get_status_display()}
- Estimated Delivery: {shipment.estimated_dropoff_time.strftime('%Y-%m-%d %H:%M') if shipment.estimated_dropoff_time else 'TBD'}

Delivery Address:
{address.street}
{address.city}, {address.region}
{address.country}
"""

            if driver:
                message += f"\nDriver: {driver.user.get_full_name()}\n"
                message += f"Phone: {driver.phone}\n"

            message += f"\nTrack your shipment: {context['tracking_url']}\n\n"
            message += "Thank you for your business!\n"

            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[buyer.email],
                fail_silently=False,
            )

        logger.info(f"Sent notification for shipment {shipment.tracking_number} to {buyer.email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email notification: {str(e)}")
        return False


def send_driver_assignment_notification(driver: Driver, shipment: Shipment) -> bool:
    """
    Send notification to driver when assigned to a shipment.

    Args:
        driver: Driver instance
        shipment: Shipment instance

    Returns:
        Boolean indicating success
    """
    try:
        subject = f"New Delivery Assignment - {shipment.tracking_number}"

        message = f"""
Hello {driver.user.get_full_name()},

You have been assigned a new delivery:

Shipment: {shipment.tracking_number}
Pickup Location: {shipment.warehouse.name if shipment.warehouse else 'TBD'}
Pickup Time: {shipment.collect_time.strftime('%Y-%m-%d %H:%M')}

Delivery Address:
{shipment.shipping_address.street}
{shipment.shipping_address.city}, {shipment.shipping_address.region}

Estimated Delivery: {shipment.estimated_dropoff_time.strftime('%Y-%m-%d %H:%M')}

Shipment Details:
- Weight: {shipment.weight_kg} kg
- Volume: {shipment.size_cubic_meters} m³
- Type: {shipment.get_shipment_type_display()}
- Material: {shipment.get_material_type_display()}

Please check the driver portal for more details and navigation information.

Best regards,
Logistics Team
"""

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[driver.user.email],
            fail_silently=False,
        )

        logger.info(f"Sent assignment notification to driver {driver.employee_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to send driver assignment notification: {str(e)}")
        return False


def send_bulk_notifications(
        shipments: List[Shipment],
        notification_type: str = 'status_update'
) -> Dict[str, int]:
    """
    Send notifications for multiple shipments.

    Args:
        shipments: List of shipment instances
        notification_type: Type of notification

    Returns:
        Dictionary with success and failure counts
    """
    results = {'success': 0, 'failed': 0}

    for shipment in shipments:
        try:
            if notification_type == 'status_update':
                success = send_delivery_notification(shipment, shipment.status)
            elif notification_type == 'driver_assignment' and shipment.driver:
                success = send_driver_assignment_notification(shipment.driver, shipment)
            else:
                success = False

            if success:
                results['success'] += 1
            else:
                results['failed'] += 1

        except Exception as e:
            logger.error(f"Failed to send notification for shipment {shipment.tracking_number}: {str(e)}")
            results['failed'] += 1

    return results


# ============================================================================
# STATUS HISTORY FUNCTIONS
# ============================================================================

def create_delivery_history(
        shipment: Shipment,
        status: str,
        user,
        notes: str = ""
) -> Optional[OrderStatusHistory]:
    """
    Create status history entry for shipment/order.

    Args:
        shipment: Shipment instance
        status: New status
        user: User making the change
        notes: Optional notes

    Returns:
        Created OrderStatusHistory instance or None
    """
    if not shipment.order:
        logger.warning(f"Cannot create history for shipment {shipment.tracking_number}: No order")
        return None

    try:
        history = OrderStatusHistory.objects.create(
            order=shipment.order,
            status=status,
            changed_by=user,
            notes=notes or f"Shipment {shipment.tracking_number} status changed to {status}"
        )

        logger.info(f"Created history entry for order {shipment.order.id}: {status}")
        return history

    except Exception as e:
        logger.error(f"Failed to create delivery history: {str(e)}")
        return None


# ============================================================================
# DRIVER STATISTICS FUNCTIONS
# ============================================================================

def get_driver_statistics(
        driver: Driver,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Get comprehensive statistics for a driver.

    Args:
        driver: Driver instance
        start_date: Optional start date for statistics
        end_date: Optional end date for statistics

    Returns:
        Dictionary containing driver statistics
    """
    # Default to last 30 days if no date range specified
    if not end_date:
        end_date = timezone.now()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    # Get shipments in date range
    shipments = driver.shipments.filter(
        created_at__range=(start_date, end_date)
    )

    # Basic counts
    total_shipments = shipments.count()
    delivered_shipments = shipments.filter(status='delivered').count()
    pending_shipments = shipments.filter(status='pending').count()
    in_transit_shipments = shipments.filter(status='in_transit').count()
    cancelled_shipments = shipments.filter(status='cancelled').count()

    # This month's statistics
    today = timezone.now().date()
    first_day_of_month = today.replace(day=1)

    this_month_deliveries = shipments.filter(
        status='delivered',
        actual_dropoff_time__date__gte=first_day_of_month
    ).count()

    # This week's statistics
    week_ago = today - timedelta(days=7)
    this_week_deliveries = shipments.filter(
        status='delivered',
        actual_dropoff_time__date__gte=week_ago
    ).count()

    # On-time delivery rate
    delivered = shipments.filter(status='delivered', actual_dropoff_time__isnull=False)
    on_time_deliveries = delivered.filter(
        actual_dropoff_time__lte=F('estimated_dropoff_time')
    ).count()

    on_time_rate = (on_time_deliveries / delivered.count() * 100) if delivered.count() > 0 else 0

    # Average delivery time
    avg_delivery_time = None
    if delivered.exists():
        total_seconds = sum(
            (s.actual_dropoff_time - s.collect_time).total_seconds()
            for s in delivered
            if s.actual_dropoff_time and s.collect_time
        )
        if total_seconds > 0:
            avg_delivery_time = round(total_seconds / delivered.count() / 3600, 2)  # Hours

    # Completion rate
    completion_rate = (delivered_shipments / total_shipments * 100) if total_shipments > 0 else 0

    return {
        'driver_name': driver.user.get_full_name(),
        'employee_id': driver.employee_id,
        'total_shipments': total_shipments,
        'delivered_shipments': delivered_shipments,
        'pending_shipments': pending_shipments,
        'in_transit_shipments': in_transit_shipments,
        'cancelled_shipments': cancelled_shipments,
        'this_month_deliveries': this_month_deliveries,
        'this_week_deliveries': this_week_deliveries,
        'on_time_rate': round(on_time_rate, 2),
        'completion_rate': round(completion_rate, 2),
        'average_delivery_time_hours': avg_delivery_time,
        'date_range': {
            'start': start_date.isoformat(),
            'end': end_date.isoformat(),
        }
    }


def get_top_performing_drivers(
        limit: int = 10,
        metric: str = 'on_time_rate'
) -> List[Dict[str, Any]]:
    """
    Get top performing drivers based on specified metric.

    Args:
        limit: Number of drivers to return
        metric: Metric to sort by ('on_time_rate', 'total_deliveries', etc.)

    Returns:
        List of driver statistics dictionaries
    """
    drivers = Driver.objects.filter(is_active=True)
    driver_stats = []

    for driver in drivers:
        stats = get_driver_statistics(driver)
        driver_stats.append(stats)

    # Sort by specified metric
    if metric == 'on_time_rate':
        driver_stats.sort(key=lambda x: x['on_time_rate'], reverse=True)
    elif metric == 'total_deliveries':
        driver_stats.sort(key=lambda x: x['delivered_shipments'], reverse=True)
    elif metric == 'completion_rate':
        driver_stats.sort(key=lambda x: x['completion_rate'], reverse=True)

    return driver_stats[:limit]


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_shipment_transition(
        current_status: str,
        new_status: str
) -> bool:
    """
    Validate if shipment can transition to new status.

    Args:
        current_status: Current shipment status
        new_status: Proposed new status

    Returns:
        Boolean indicating if transition is valid
    """
    # Define valid status transitions
    valid_transitions = {
        'pending': ['shipped', 'cancelled'],
        'shipped': ['in_transit', 'cancelled'],
        'in_transit': ['delivered', 'returned'],
        'delivered': [],  # Final status
        'cancelled': [],  # Final status
        'returned': ['pending'],  # Can restart
    }

    allowed_statuses = valid_transitions.get(current_status, [])
    return new_status in allowed_statuses


def validate_driver_assignment(
        driver: Driver,
        shipment: Shipment
) -> Tuple[bool, Optional[str]]:
    """
    Validate if driver can be assigned to shipment.

    Args:
        driver: Driver instance
        shipment: Shipment instance

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check if driver is active
    if not driver.is_active:
        return False, "Driver is not active"

    # Check license validity
    if not driver.is_license_valid():
        return False, "Driver's license has expired"

    # Check driver workload
    active_shipments = driver.shipments.filter(
        status__in=['pending', 'in_transit', 'shipped']
    ).count()

    max_concurrent = getattr(settings, 'MAX_DRIVER_CONCURRENT_SHIPMENTS', 10)
    if active_shipments >= max_concurrent:
        return False, f"Driver has reached maximum concurrent shipments ({max_concurrent})"

    # Check if shipment is assignable
    if shipment.status not in ['pending', 'shipped']:
        return False, f"Shipment with status '{shipment.status}' cannot be assigned"

    return True, None


def validate_vehicle_capacity(
        vehicle: Vehicle,
        shipment: Shipment
) -> Tuple[bool, Optional[str]]:
    """
    Validate if vehicle has sufficient capacity for shipment.

    Args:
        vehicle: Vehicle instance
        shipment: Shipment instance

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check weight capacity
    if shipment.weight_kg > vehicle.capacity_kg:
        return False, f"Shipment weight ({shipment.weight_kg}kg) exceeds vehicle capacity ({vehicle.capacity_kg}kg)"

    # Check volume capacity
    if vehicle.capacity_cubic_meters:
        if shipment.size_cubic_meters > vehicle.capacity_cubic_meters:
            return False, f"Shipment volume ({shipment.size_cubic_meters}m³) exceeds vehicle capacity ({vehicle.capacity_cubic_meters}m³)"

    # Check vehicle status
    if not vehicle.is_active:
        return False, "Vehicle is not active"

    if vehicle.needs_maintenance():
        return False, "Vehicle needs maintenance"

    return True, None


# ============================================================================
# ASSIGNMENT FUNCTIONS
# ============================================================================

@transaction.atomic
def assign_shipment_to_driver(
        shipment_id: int,
        driver_id: int,
        vehicle_id: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Assign a shipment to a driver with comprehensive validation.

    Args:
        shipment_id: Shipment ID
        driver_id: Driver ID
        vehicle_id: Optional vehicle ID

    Returns:
        Tuple of (success, message)
    """
    try:
        shipment = Shipment.objects.select_for_update().get(id=shipment_id)
        driver = Driver.objects.get(id=driver_id)

        # Validate driver assignment
        is_valid, error = validate_driver_assignment(driver, shipment)
        if not is_valid:
            return False, error

        # Assign driver
        shipment.driver = driver

        # Assign vehicle if provided
        if vehicle_id:
            vehicle = Vehicle.objects.get(id=vehicle_id)
            is_valid, error = validate_vehicle_capacity(vehicle, shipment)
            if not is_valid:
                return False, error
            shipment.vehicle = vehicle

        shipment.save()

        # Send notification
        send_driver_assignment_notification(driver, shipment)

        logger.info(f"Assigned shipment {shipment.tracking_number} to driver {driver.employee_id}")

        return True, "Shipment assigned successfully"

    except Shipment.DoesNotExist:
        return False, "Shipment not found"
    except Driver.DoesNotExist:
        return False, "Driver not found"
    except Vehicle.DoesNotExist:
        return False, "Vehicle not found"
    except Exception as e:
        logger.error(f"Error assigning shipment: {str(e)}")
        return False, f"An error occurred: {str(e)}"


def auto_assign_optimal_driver(shipment: Shipment) -> Tuple[bool, str]:
    """
    Automatically assign the most suitable driver to a shipment.

    Uses algorithm to find driver with:
    - Least current workload
    - Valid license
    - Active status
    - Available vehicle

    Args:
        shipment: Shipment instance

    Returns:
        Tuple of (success, message)
    """
    # Get available drivers
    available_drivers = Driver.objects.filter(
        is_active=True
    ).annotate(
        active_shipments_count=Count(
            'shipments',
            filter=Q(shipments__status__in=['pending', 'in_transit', 'shipped'])
        )
    ).filter(
        active_shipments_count__lt=getattr(settings, 'MAX_DRIVER_CONCURRENT_SHIPMENTS', 10)
    ).order_by('active_shipments_count')

    # Filter drivers with valid licenses
    available_drivers = [d for d in available_drivers if d.is_license_valid()]

    if not available_drivers:
        return False, "No available drivers found"

    # Get best driver (least loaded)
    best_driver = available_drivers[0]

    # Find suitable vehicle
    suitable_vehicle = Vehicle.objects.filter(
        driver=best_driver,
        is_active=True,
        capacity_kg__gte=shipment.weight_kg
    ).first()

    if not suitable_vehicle:
        # Try unassigned vehicles
        suitable_vehicle = Vehicle.objects.filter(
            driver__isnull=True,
            is_active=True,
            capacity_kg__gte=shipment.weight_kg
        ).first()

    # Assign
    shipment.driver = best_driver
    if suitable_vehicle:
        shipment.vehicle = suitable_vehicle
    shipment.save()

    # Notify
    send_driver_assignment_notification(best_driver, shipment)

    logger.info(
        f"Auto-assigned shipment {shipment.tracking_number} to driver {best_driver.employee_id}"
    )

    return True, f"Assigned to driver {best_driver.employee_id}"


@transaction.atomic
def bulk_update_shipment_status(
        shipment_ids: List[int],
        new_status: str,
        user,
        send_notifications: bool = True
) -> Dict[str, int]:
    """
    Bulk update multiple shipments status with validation.

    Args:
        shipment_ids: List of shipment IDs
        new_status: New status to set
        user: User performing the update
        send_notifications: Whether to send notifications

    Returns:
        Dictionary with update statistics
    """
    results = {'updated': 0, 'failed': 0, 'skipped': 0}

    shipments = Shipment.objects.filter(id__in=shipment_ids)

    for shipment in shipments:
        # Validate transition
        if not validate_shipment_transition(shipment.status, new_status):
            logger.warning(
                f"Invalid transition for shipment {shipment.tracking_number}: "
                f"{shipment.status} -> {new_status}"
            )
            results['skipped'] += 1
            continue

        try:
            # Update status
            old_status = shipment.status
            shipment.status = new_status
            shipment.save()

            # Create history entry
            create_delivery_history(
                shipment,
                new_status,
                user,
                f"Bulk status update from {old_status} to {new_status}"
            )

            # Send notification
            if send_notifications:
                send_delivery_notification(shipment, new_status, shipment.driver)

            results['updated'] += 1

        except Exception as e:
            logger.error(f"Failed to update shipment {shipment.tracking_number}: {str(e)}")
            results['failed'] += 1

    return results


# ============================================================================
# GEOCODING FUNCTIONS
# ============================================================================

def calculate_distance_haversine(
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float
) -> float:
    """
    Calculate distance between two coordinates using Haversine formula.

    Args:
        lat1: Origin latitude
        lon1: Origin longitude
        lat2: Destination latitude
        lon2: Destination longitude

    Returns:
        Distance in kilometers
    """
    # Earth radius in kilometers
    R = 6371.0

    # Convert to radians
    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)

    # Differences
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    # Haversine formula
    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance = R * c
    return round(distance, 2)


def geocode_address(
        address: str,
        use_google: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Geocode an address to get coordinates.

    Args:
        address: Address string
        use_google: Whether to use Google Geocoding API

    Returns:
        Dictionary with lat, lng, and formatted_address or None
    """
    if use_google and hasattr(settings, 'GOOGLE_MAPS_API_KEY'):
        try:
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                'address': address,
                'key': settings.GOOGLE_MAPS_API_KEY
            }

            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data['status'] == 'OK' and data['results']:
                result = data['results'][0]
                location = result['geometry']['location']

                return {
                    'lat': location['lat'],
                    'lng': location['lng'],
                    'formatted_address': result['formatted_address'],
                    'accuracy': 'high',
                    'source': 'google'
                }
        except Exception as e:
            logger.error(f"Geocoding error: {str(e)}")

    return None


def validate_plus_code(plus_code: str) -> bool:
    """
    Validate Plus Code format.

    Args:
        plus_code: Plus Code string

    Returns:
        Boolean indicating if format is valid
    """
    if not plus_code:
        return False

    try:
        # Valid Plus Code characters
        valid_chars = set('23456789CFGHJMPQRVWX+')

        # Remove spaces and convert to uppercase
        code = plus_code.replace(' ', '').upper()

        # Check characters
        if not all(c in valid_chars for c in code):
            return False

        # Check for + symbol
        if '+' not in code:
            return False

        # Split on +
        parts = code.split('+')
        if len(parts) != 2:
            return False

        # Length checks
        if not (4 <= len(parts[0]) <= 8):
            return False
        if not (1 <= len(parts[1]) <= 3):
            return False

        # Use library if available
        try:
            import openlocationcode as olc
            return olc.isValid(code)
        except ImportError:
            return True  # Basic validation passed

    except Exception as e:
        logger.error(f"Plus code validation error: {str(e)}")
        return False


def decode_plus_code(
        plus_code: str,
        reference_location: Optional[Tuple[float, float]] = None
) -> Optional[Tuple[float, float]]:
    """
    Decode Plus Code to coordinates.

    Args:
        plus_code: Plus Code string
        reference_location: Optional (lat, lng) for short codes

    Returns:
        Tuple of (latitude, longitude) or None
    """
    try:
        import openlocationcode as olc

        code_area = olc.decode(plus_code)
        center_lat = code_area.latitudeCenter
        center_lng = code_area.longitudeCenter

        return (center_lat, center_lng)

    except ImportError:
        logger.warning("openlocationcode library not installed")
        # Fallback to API
        if hasattr(settings, 'GOOGLE_MAPS_API_KEY'):
            try:
                url = "https://maps.googleapis.com/maps/api/geocode/json"
                params = {
                    'address': plus_code,
                    'key': settings.GOOGLE_MAPS_API_KEY
                }

                response = requests.get(url, params=params, timeout=10)
                data = response.json()

                if data['status'] == 'OK' and data['results']:
                    location = data['results'][0]['geometry']['location']
                    return (location['lat'], location['lng'])

            except Exception as e:
                logger.error(f"Plus code decode error: {str(e)}")

        return None
    except Exception as e:
        logger.error(f"Plus code decode error: {str(e)}")
        return None


def get_shipment_location_data(shipment: Shipment) -> Dict[str, Any]:
    """
    Get comprehensive location data for a shipment.

    Args:
        shipment: Shipment instance

    Returns:
        Dictionary with location data
    """
    address = shipment.shipping_address

    result = {
        'shipment_id': shipment.id,
        'tracking_number': shipment.tracking_number,
        'customer_name': address.full_name,
        'phone': address.phone_number,
        'address': {
            'street': address.street,
            'city': address.city,
            'region': address.region,
            'country': address.country,
            'geo_code': getattr(address, 'geo_code', None),
            'full_address': f"{address.street}, {address.city}, {address.region}, {address.country}",
        },
        'shipment_details': {
            'weight_kg': float(shipment.weight_kg),
            'size_cubic_meters': float(shipment.size_cubic_meters),
            'material_type': shipment.get_material_type_display(),
            'shipment_type': shipment.get_shipment_type_display(),
            'status': shipment.status,
            'estimated_delivery': shipment.estimated_dropoff_time.isoformat() if shipment.estimated_dropoff_time else None,
        }
    }

    # Try to get coordinates
    geo_code = getattr(address, 'geo_code', None)
    coordinates = None

    if geo_code and validate_plus_code(geo_code):
        # Decode Plus Code
        coords = decode_plus_code(geo_code)
        if coords:
            coordinates = {
                'lat': coords[0],
                'lng': coords[1],
                'source': 'plus_code',
                'accuracy': 'high'
            }

    if not coordinates:
        # Try geocoding address
        location = geocode_address(result['address']['full_address'])
        if location:
            coordinates = {
                'lat': location['lat'],
                'lng': location['lng'],
                'source': location.get('source', 'geocoded'),
                'accuracy': location.get('accuracy', 'medium')
            }

    if coordinates:
        result['coordinates'] = coordinates

        # Generate map URLs
        result['maps_urls'] = {
            'directions': f"https://www.google.com/maps/dir/?api=1&destination={coordinates['lat']},{coordinates['lng']}",
            'view': f"https://www.google.com/maps?q={coordinates['lat']},{coordinates['lng']}",
            'plus_code_url': f"https://plus.codes/{geo_code}" if geo_code else None,
        }

    return result


# ============================================================================
# COST CALCULATION FUNCTIONS
# ============================================================================

def calculate_shipping_cost(shipment: Shipment) -> Decimal:
    """
    Calculate shipping cost for a shipment.

    Args:
        shipment: Shipment instance

    Returns:
        Calculated cost as Decimal
    """
    from .services import PricingService

    # Get distance if possible
    distance_km = None
    if shipment.warehouse and hasattr(shipment.shipping_address, 'latitude'):
        if shipment.warehouse.latitude and shipment.shipping_address.latitude:
            distance_km = calculate_distance_haversine(
                float(shipment.warehouse.latitude),
                float(shipment.warehouse.longitude),
                float(shipment.shipping_address.latitude),
                float(shipment.shipping_address.longitude)
            )

    return PricingService.calculate_shipping_cost(
        shipment_type=shipment.shipment_type,
        weight_kg=shipment.weight_kg,
        volume_cubic_meters=shipment.size_cubic_meters,
        distance_km=distance_km
    )


# ============================================================================
# UTILITY HELPER FUNCTIONS
# ============================================================================

def get_optimal_route(shipments: List[Shipment]) -> List[Shipment]:
    """
    Optimize route for multiple deliveries (placeholder implementation).

    Args:
        shipments: List of shipment instances

    Returns:
        Optimized list of shipments
    """
    # This is a placeholder - implement proper route optimization
    # In production, use:
    # - Google Routes API
    # - GraphHopper
    # - OR-Tools
    # - Custom TSP/VRP algorithms

    return sorted(shipments, key=lambda s: s.estimated_dropoff_time)


def generate_tracking_number() -> str:
    """
    Generate a unique tracking number.

    Returns:
        Unique tracking number string
    """
    import uuid
    timestamp = int(timezone.now().timestamp())
    unique_id = str(uuid.uuid4().hex[:8]).upper()
    return f"TRK{timestamp}{unique_id}"


def format_delivery_time_estimate(shipment: Shipment) -> str:
    """
    Format delivery time estimate in human-readable format.

    Args:
        shipment: Shipment instance

    Returns:
        Formatted time estimate string
    """
    if not shipment.estimated_dropoff_time:
        return "TBD"

    now = timezone.now()
    time_diff = shipment.estimated_dropoff_time - now

    if time_diff.total_seconds() < 0:
        return "Overdue"

    hours = int(time_diff.total_seconds() / 3600)

    if hours < 1:
        minutes = int(time_diff.total_seconds() / 60)
        return f"{minutes} minutes"
    elif hours < 24:
        return f"{hours} hours"
    else:
        days = hours // 24
        return f"{days} days"


def enhance_delivery_instructions(shipment) -> Dict[str, Any]:
    """
    Generate comprehensive, context-aware delivery instructions for a shipment.
    Combines multiple instruction sources into a single, prioritized guide.

    Args:
        shipment: Shipment instance

    Returns:
        Dictionary containing categorized delivery instructions:
        {
            'priority': ['Urgent instruction 1', ...],  # High priority warnings
            'handling': ['Handle with care', ...],      # Handling instructions
            'location': ['GPS coordinates', ...],        # Navigation help
            'timing': ['Deliver before 5 PM', ...],     # Time-related notes
            'contact': ['Call customer', ...],          # Customer contact info
            'special': ['Ring doorbell twice', ...],    # Special requests
            'all_instructions': [...],                  # All instructions combined
            'instruction_count': 12                     # Total count
        }

    Example:
        instructions = enhance_delivery_instructions(shipment)
        for priority_item in instructions['priority']:
            print(f"⚠️ {priority_item}")
    """

    instructions = {
        'priority': [],
        'handling': [],
        'location': [],
        'timing': [],
        'contact': [],
        'special': [],
    }

    # ========================================================================
    # PRIORITY INSTRUCTIONS (Urgent/Critical)
    # ========================================================================

    # Time-critical deliveries
    if shipment.estimated_dropoff_time:
        now = timezone.now()
        time_until = shipment.estimated_dropoff_time - now
        minutes_until = time_until.total_seconds() / 60

        if minutes_until < 30:
            instructions['priority'].append(
                f"🚨 URGENT: Deliver within {int(minutes_until)} minutes!"
            )
        elif minutes_until < 60:
            instructions['priority'].append(
                f"⏰ TIME SENSITIVE: Less than 1 hour until delivery window"
            )
        elif minutes_until < 120:
            instructions['priority'].append(
                f"⏰ Deliver within 2 hours (by {shipment.estimated_dropoff_time.strftime('%I:%M %p')})"
            )

    # Heavy items
    if shipment.weight_kg > 50:
        instructions['priority'].append(
            f"⚠️ HEAVY: {shipment.weight_kg} kg - Assistance may be required"
        )

    # Hazardous materials
    if shipment.material_type == 'hazardous':
        instructions['priority'].append(
            "☢️ HAZARDOUS MATERIAL - Follow all safety protocols"
        )

    # ========================================================================
    # HANDLING INSTRUCTIONS
    # ========================================================================

    # Material-specific handling
    material_handling = {
        'fragile': "🔴 FRAGILE - Handle with extreme care, no rough handling",
        'liquid': "💧 LIQUID - Keep upright, avoid tilting or shaking",
        'electronic': "⚡ ELECTRONICS - Protect from moisture and impacts",
        'perishable': "❄️ PERISHABLE - Maintain temperature, deliver ASAP",
        'document': "📄 DOCUMENTS - Keep dry and flat",
        'general': "📦 STANDARD - Normal handling procedures"
    }

    if shipment.material_type in material_handling:
        instructions['handling'].append(material_handling[shipment.material_type])

    # Weight handling
    if 20 < shipment.weight_kg <= 50:
        instructions['handling'].append(
            f"⚖️ MODERATE WEIGHT: {shipment.weight_kg} kg - Use proper lifting technique"
        )
    elif shipment.weight_kg <= 20:
        instructions['handling'].append(
            f"✅ LIGHT WEIGHT: {shipment.weight_kg} kg - Standard handling"
        )

    # Size handling
    if shipment.size_cubic_meters > 1.0:
        instructions['handling'].append(
            f"📦 LARGE PACKAGE: {shipment.size_cubic_meters} m³ - May need assistance"
        )

    # Multiple boxes
    box_count = shipment.boxes.count() if hasattr(shipment, 'boxes') else 0
    if box_count > 1:
        instructions['handling'].append(
            f"📦 MULTIPLE BOXES: {box_count} boxes total - Verify all delivered"
        )

        # List box numbers if available
        if box_count <= 10:  # Only list if reasonable number
            box_numbers = list(shipment.boxes.values_list('box_number', flat=True))
            instructions['handling'].append(
                f"   Box numbers: {', '.join(map(str, box_numbers))}"
            )

    # ========================================================================
    # LOCATION INSTRUCTIONS
    # ========================================================================

    address = shipment.shipping_address
    if address:
        # Full address
        full_address = f"{address.address}, {address.city}, {address.region}"
        instructions['location'].append(f"📍 DESTINATION: {full_address}")

        # Plus Code if available
        if hasattr(address, 'geo_code') and address.geo_code:
            from .utils import validate_plus_code
            if validate_plus_code(address.geo_code):
                instructions['location'].append(
                    f"➕ Plus Code: {address.geo_code} (Use for precise navigation)"
                )

        # GPS coordinates if available
        if hasattr(address, 'latitude') and hasattr(address, 'longitude'):
            if address.latitude and address.longitude:
                instructions['location'].append(
                    f"🗺️ GPS: {address.latitude}, {address.longitude}"
                )

        # Landmarks from address notes
        if hasattr(address, 'landmark') and address.landmark:
            instructions['location'].append(
                f"🏛️ LANDMARK: {address.landmark}"
            )

        # Building/apartment info
        if hasattr(address, 'apartment_number') and address.apartment_number:
            instructions['location'].append(
                f"🏢 UNIT: {address.apartment_number}"
            )

        # Floor information
        if hasattr(address, 'floor') and address.floor:
            instructions['location'].append(
                f"🪜 FLOOR: {address.floor}"
            )

    # Warehouse pickup location
    if shipment.warehouse:
        warehouse = shipment.warehouse
        instructions['location'].append(
            f"📦 PICKUP FROM: {warehouse.name} ({warehouse.address})"
        )

    # ========================================================================
    # TIMING INSTRUCTIONS
    # ========================================================================

    now = timezone.now()
    hour = now.hour

    # Time of day considerations
    if 6 <= hour < 9:
        instructions['timing'].append(
            "🌅 MORNING DELIVERY - Customer may be preparing for work"
        )
    elif 9 <= hour < 12:
        instructions['timing'].append(
            "☀️ MID-MORNING - Good time for deliveries"
        )
    elif 12 <= hour < 14:
        instructions['timing'].append(
            "🍽️ LUNCH TIME - Customer may be unavailable, try calling first"
        )
    elif 14 <= hour < 17:
        instructions['timing'].append(
            "☀️ AFTERNOON - Good time for deliveries"
        )
    elif 17 <= hour < 20:
        instructions['timing'].append(
            "🌆 EVENING RUSH - Heavy traffic expected, allow extra time"
        )
    elif 20 <= hour or hour < 6:
        instructions['timing'].append(
            "🌙 LATE/EARLY - Verify customer expects delivery at this time"
        )

    # Day of week
    weekday = now.weekday()
    weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    if weekday >= 5:  # Weekend
        instructions['timing'].append(
            f"📅 WEEKEND ({weekday_names[weekday]}) - Confirm customer is home"
        )
    else:
        instructions['timing'].append(
            f"📅 WEEKDAY ({weekday_names[weekday]}) - Business hours delivery"
        )

    # Estimated delivery time window
    if shipment.estimated_dropoff_time:
        delivery_time = shipment.estimated_dropoff_time.strftime('%I:%M %p')
        instructions['timing'].append(
            f"⏰ ESTIMATED DELIVERY: {delivery_time}"
        )

    # ========================================================================
    # CONTACT INSTRUCTIONS
    # ========================================================================

    # Customer information
    if shipment.order and shipment.order.buyer:
        buyer = shipment.order.buyer
        customer_name = buyer.get_full_name() or buyer.username
        instructions['contact'].append(f"👤 CUSTOMER: {customer_name}")

        if hasattr(buyer, 'phone') and buyer.phone:
            instructions['contact'].append(f"📞 PHONE: {buyer.phone}")
        elif address and hasattr(address, 'phone') and address.phone:
            instructions['contact'].append(f"📞 PHONE: {address.phone}")

    # No phone warning
    if not any('PHONE' in inst for inst in instructions['contact']):
        instructions['contact'].append(
            "⚠️ NO PHONE NUMBER - May be difficult to contact customer"
        )

    # Driver instructions
    if shipment.driver:
        instructions['contact'].append(
            f"🚚 DRIVER: {shipment.driver.user.get_full_name()}"
        )

    # ========================================================================
    # SPECIAL INSTRUCTIONS
    # ========================================================================

    # Custom delivery notes from shipment
    if hasattr(shipment, 'delivery_notes') and shipment.delivery_notes:
        instructions['special'].append(
            f"📝 DELIVERY NOTES: {shipment.delivery_notes}"
        )

    # Order notes
    if shipment.order and hasattr(shipment.order, 'notes') and shipment.order.notes:
        instructions['special'].append(
            f"📋 ORDER NOTES: {shipment.order.notes}"
        )

    # Address-specific instructions
    if address:
        if hasattr(address, 'delivery_instructions') and address.delivery_instructions:
            instructions['special'].append(
                f"🏠 ADDRESS NOTES: {address.delivery_instructions}"
            )

        # Access codes
        if hasattr(address, 'access_code') and address.access_code:
            instructions['special'].append(
                f"🔐 ACCESS CODE: {address.access_code}"
            )

        # Gate code
        if hasattr(address, 'gate_code') and address.gate_code:
            instructions['special'].append(
                f"🚪 GATE CODE: {address.gate_code}"
            )

    # Signature requirements
    if hasattr(shipment, 'requires_signature') and shipment.requires_signature:
        instructions['special'].append(
            "✍️ SIGNATURE REQUIRED - Must obtain recipient signature"
        )

    # Photo proof
    if hasattr(shipment, 'requires_photo') and shipment.requires_photo:
        instructions['special'].append(
            "📸 PHOTO REQUIRED - Take photo proof of delivery"
        )

    # ========================================================================
    # COMPILE ALL INSTRUCTIONS
    # ========================================================================

    # Combine all instructions in priority order
    all_instructions = (
            instructions['priority'] +
            instructions['handling'] +
            instructions['location'] +
            instructions['contact'] +
            instructions['timing'] +
            instructions['special']
    )

    instructions['all_instructions'] = all_instructions
    instructions['instruction_count'] = len(all_instructions)

    # Add summary
    instructions['summary'] = _generate_instruction_summary(instructions)

    return instructions


def _generate_instruction_summary(instructions: Dict[str, List[str]]) -> str:
    """
    Generate a brief summary of the most important instructions.

    Args:
        instructions: Dictionary of categorized instructions

    Returns:
        Brief summary string
    """
    summary_parts = []

    # Priority items
    if instructions['priority']:
        summary_parts.append(f"{len(instructions['priority'])} urgent items")

    # Handling
    if instructions['handling']:
        summary_parts.append("special handling required")

    # Contact issues
    if any('NO PHONE' in inst for inst in instructions['contact']):
        summary_parts.append("no phone contact")

    if summary_parts:
        return "ATTENTION: " + ", ".join(summary_parts)
    else:
        return "Standard delivery - follow normal procedures"


def format_delivery_instructions_text(instructions: Dict[str, Any]) -> str:
    """
    Format delivery instructions as plain text for printing or display.

    Args:
        instructions: Dictionary from enhance_delivery_instructions()

    Returns:
        Formatted text string
    """
    lines = []
    lines.append("=" * 60)
    lines.append("DELIVERY INSTRUCTIONS")
    lines.append("=" * 60)
    lines.append("")

    # Add each category
    categories = [
        ('PRIORITY ALERTS', 'priority'),
        ('HANDLING INSTRUCTIONS', 'handling'),
        ('LOCATION DETAILS', 'location'),
        ('CONTACT INFORMATION', 'contact'),
        ('TIMING NOTES', 'timing'),
        ('SPECIAL INSTRUCTIONS', 'special'),
    ]

    for title, key in categories:
        if instructions[key]:
            lines.append(f"--- {title} ---")
            for instruction in instructions[key]:
                lines.append(f"  {instruction}")
            lines.append("")

    lines.append("=" * 60)
    lines.append(f"Total Instructions: {instructions['instruction_count']}")
    lines.append(f"Summary: {instructions['summary']}")
    lines.append("=" * 60)

    return "\n".join(lines)


def format_delivery_instructions_html(instructions: Dict[str, Any]) -> str:
    """
    Format delivery instructions as HTML for web display.

    Args:
        instructions: Dictionary from enhance_delivery_instructions()

    Returns:
        HTML string
    """
    html = ['<div class="delivery-instructions">']
    html.append('<h3>Delivery Instructions</h3>')

    categories = [
        ('Priority Alerts', 'priority', 'danger'),
        ('Handling Instructions', 'handling', 'warning'),
        ('Location Details', 'location', 'info'),
        ('Contact Information', 'contact', 'primary'),
        ('Timing Notes', 'timing', 'secondary'),
        ('Special Instructions', 'special', 'success'),
    ]

    for title, key, badge_class in categories:
        if instructions[key]:
            html.append(f'<div class="instruction-category">')
            html.append(f'<h4><span class="badge bg-{badge_class}">{title}</span></h4>')
            html.append('<ul class="list-group">')

            for instruction in instructions[key]:
                html.append(f'<li class="list-group-item">{instruction}</li>')

            html.append('</ul>')
            html.append('</div>')

    html.append(f'<div class="alert alert-info mt-3">')
    html.append(f'<strong>Summary:</strong> {instructions["summary"]}')
    html.append('</div>')
    html.append('</div>')

    return '\n'.join(html)


# Export functions
__all__ = [
    'enhance_delivery_instructions',
    'format_delivery_instructions_text',
    'format_delivery_instructions_html',
]

