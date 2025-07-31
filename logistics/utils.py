import requests
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from .models import Shipment, Driver
from orders.models import OrderStatusHistory

def send_delivery_notification(shipment, status, driver=None):
    """
    Send email notification when shipment status changes
    """
    if not shipment.order or not shipment.order.buyer.email:
        return False

    status_messages = {
        'in_transit': 'Your order is now out for delivery',
        'delivered': 'Your order has been delivered successfully'
    }

    subject = f"Order Update - Shipment #{shipment.id}"
    message = f"""
    Dear {shipment.shipping_address.full_name},

    {status_messages.get(status, 'Your order status has been updated')}.

    Shipment Details:
    - Shipment ID: #{shipment.id}
    - Status: {shipment.get_status_display()}
    - Expected Delivery: {shipment.estimated_dropoff_time}

    Delivery Address:
    {shipment.shipping_address.street}
    {shipment.shipping_address.city}, {shipment.shipping_address.region}

    """

    if driver:
        message += f"Driver: {driver.user.get_full_name()}\n"
        message += f"Phone: {driver.phone}\n"

    message += "\nThank you for your business!"

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [shipment.order.buyer.email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def create_delivery_history(shipment, status, user, notes=""):
    """
    Create status history entry for shipment/order
    """
    if shipment.order:
        OrderStatusHistory.objects.create(
            order=shipment.order,
            status=status,
            changed_by=user,
            notes=notes
        )


def get_driver_statistics(driver):
    """
    Get comprehensive statistics for a driver
    """
    from django.db.models import Count, Q
    from datetime import datetime, timedelta

    # Get all shipments for this driver
    shipments = Shipment.objects.filter(driver=driver)

    # Basic counts
    total_shipments = shipments.count()
    pending_shipments = shipments.filter(status='pending').count()
    in_transit_shipments = shipments.filter(status='in_transit').count()
    delivered_shipments = shipments.filter(status='shipped').count()

    # This month's statistics
    today = timezone.now().date()
    first_day_of_month = today.replace(day=1)

    this_month_deliveries = shipments.filter(
        status='shipped',
        created_at__date__gte=first_day_of_month
    ).count()

    # This week's statistics
    week_ago = today - timedelta(days=7)
    this_week_deliveries = shipments.filter(
        status='shipped',
        created_at__date__gte=week_ago
    ).count()

    # Average delivery time (if you track start and completion times)
    # You might need to add timing fields to track this properly

    return {
        'total_shipments': total_shipments,
        'pending_shipments': pending_shipments,
        'in_transit_shipments': in_transit_shipments,
        'delivered_shipments': delivered_shipments,
        'this_month_deliveries': this_month_deliveries,
        'this_week_deliveries': this_week_deliveries,
        'completion_rate': (delivered_shipments / total_shipments * 100) if total_shipments > 0 else 0,
    }


def validate_shipment_transition(shipment, new_status):
    """
    Validate if shipment can transition to new status
    """
    valid_transitions = {
        'pending': ['in_transit'],
        'in_transit': ['shipped'],
        'shipped': []  # Final status
    }

    current_status = shipment.status
    allowed_statuses = valid_transitions.get(current_status, [])

    return new_status in allowed_statuses


def assign_shipment_to_driver(shipment_id, driver_id):
    """
    Assign a shipment to a driver with validation
    """
    try:
        shipment = Shipment.objects.get(id=shipment_id)
        driver = Driver.objects.get(id=driver_id)

        # Check if shipment is available for assignment
        if shipment.status != 'pending':
            return False, "Shipment is not available for assignment"

        # Check if driver is available (you can add more complex logic here)
        active_shipments = Shipment.objects.filter(
            driver=driver,
            status__in=['pending', 'in_transit']
        ).count()

        # Assuming a driver can handle max 10 active shipments
        if active_shipments >= 10:
            return False, "Driver has too many active shipments"

        # Assign the shipment
        shipment.driver = driver
        shipment.save()

        return True, "Shipment assigned successfully"

    except (Shipment.DoesNotExist, Driver.DoesNotExist):
        return False, "Shipment or Driver not found"


def get_nearby_shipments(driver, radius_km=10):
    """
    Get shipments near the driver's current location
    This is a basic implementation - for production use proper geospatial queries
    """
    # This would require implementing geolocation tracking for drivers
    # and using PostGIS or similar for spatial queries

    # For now, return shipments in the same city/region
    driver_shipments = Shipment.objects.filter(driver=driver)

    if driver_shipments.exists():
        # Get regions where driver has delivered before
        regions = driver_shipments.values_list(
            'shipping_address__region', flat=True
        ).distinct()

        # Find pending shipments in same regions
        nearby_shipments = Shipment.objects.filter(
            shipping_address__region__in=regions,
            status='pending',
            driver__isnull=True
        )

        return nearby_shipments

    return Shipment.objects.none()


def bulk_update_shipment_status(shipment_ids, new_status, user):
    """
    Bulk update multiple shipments status
    """
    shipments = Shipment.objects.filter(id__in=shipment_ids)
    updated_count = 0

    for shipment in shipments:
        if validate_shipment_transition(shipment, new_status):
            shipment.status = new_status
            shipment.save()

            # Create history entry
            create_delivery_history(
                shipment,
                new_status,
                user,
                f"Bulk status update to {new_status}"
            )

            # Send notification
            send_delivery_notification(shipment, new_status, shipment.driver)

            updated_count += 1

    return updated_count

def decode_plus_code(plus_code, reference_location=None):
    """
    Decode a Plus Code to latitude and longitude coordinates

    Args:
        plus_code (str): The Plus Code (e.g., "C7QM+F7B")
        reference_location (tuple): Optional reference (lat, lng) for short codes

    Returns:
        tuple: (latitude, longitude) or (None, None) if failed
    """
    try:
        # For Google Plus Codes, we can use the Open Location Code library
        # Or make a request to Google's geocoding API

        # Method 1: Using Google Geocoding API (requires API key)
        if hasattr(settings, 'GOOGLE_MAPS_API_KEY') and settings.GOOGLE_MAPS_API_KEY:
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                'address': plus_code,
                'key': settings.GOOGLE_MAPS_API_KEY
            }

            response = requests.get(url, params=params)
            data = response.json()

            if data['status'] == 'OK' and data['results']:
                location = data['results'][0]['geometry']['location']
                return location['lat'], location['lng']

        # Method 2: Using Open Location Code library (free, but needs installation)
        # pip install openlocationcode
        try:
            import openlocationcode as olc

            # If it's a short code, we need a reference location
            if len(plus_code) < 8 and reference_location:
                # Add reference location to make it a full code
                full_code = olc.recoverNearest(plus_code, reference_location[0], reference_location[1])
                decoded = olc.decode(full_code)
            else:
                decoded = olc.decode(plus_code)

            # Return center of the decoded area
            center_lat = (decoded.latitudeLo + decoded.latitudeHi) / 2
            center_lng = (decoded.longitudeLo + decoded.longitudeHi) / 2

            return center_lat, center_lng

        except ImportError:
            print("openlocationcode library not installed. Install with: pip install openlocationcode")

        # Method 3: Simple approximation for Gambia Plus Codes (fallback)
        # This is a rough approximation and should be replaced with proper decoding
        if plus_code.startswith('C7'):  # Gambia region codes typically start with C7
            # This is a very rough approximation - use proper decoding in production
            gambia_center = (13.4432, -15.3101)  # Approximate center of Gambia
            return gambia_center

    except Exception as e:
        print(f"Error decoding Plus Code {plus_code}: {e}")

    return None, None


def geocode_address_with_plus_code(address, geo_code=None):
    """
    Enhanced geocoding that handles both traditional addresses and Plus Codes

    Args:
        address (str): Traditional street address
        geo_code (str): Plus Code or other geocode

    Returns:
        dict: {'lat': float, 'lng': float, 'accuracy': str} or None
    """
    # First try to decode Plus Code if provided
    if geo_code:
        lat, lng = decode_plus_code(geo_code)
        if lat and lng:
            return {
                'lat': lat,
                'lng': lng,
                'accuracy': 'plus_code',
                'source': 'Plus Code'
            }

    # Fallback to traditional geocoding
    try:
        # Try Google Geocoding API first
        if hasattr(settings, 'GOOGLE_MAPS_API_KEY') and settings.GOOGLE_MAPS_API_KEY:
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                'address': f"{address}, Gambia",  # Add country for better results
                'key': settings.GOOGLE_MAPS_API_KEY
            }

            response = requests.get(url, params=params)
            data = response.json()

            if data['status'] == 'OK' and data['results']:
                location = data['results'][0]['geometry']['location']
                return {
                    'lat': location['lat'],
                    'lng': location['lng'],
                    'accuracy': 'google_geocoding',
                    'source': 'Google Geocoding'
                }

        # Fallback to OpenStreetMap Nominatim
        encoded_address = requests.utils.quote(f"{address}, Gambia")
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={encoded_address}&limit=1"

        response = requests.get(url, headers={'User-Agent': 'Driver-App/1.0'})
        data = response.json()

        if data:
            return {
                'lat': float(data[0]['lat']),
                'lng': float(data[0]['lon']),
                'accuracy': 'osm_nominatim',
                'source': 'OpenStreetMap'
            }

    except Exception as e:
        print(f"Geocoding error: {e}")

    return None


def validate_plus_code(plus_code):
    """
    Validate if a string is a valid Plus Code

    Args:
        plus_code (str): The code to validate

    Returns:
        bool: True if valid Plus Code format
    """
    if not plus_code:
        return False

    try:
        # Basic format validation
        # Plus codes contain only: 23456789CFGHJMPQRVWX+
        valid_chars = set('23456789CFGHJMPQRVWX+')

        # Remove any spaces
        code = plus_code.replace(' ', '').upper()

        # Check if all characters are valid
        if not all(c in valid_chars for c in code):
            return False

        # Check basic structure
        if '+' not in code:
            return False

        # Split on +
        parts = code.split('+')
        if len(parts) != 2:
            return False

        # Basic length checks
        if len(parts[0]) < 4 or len(parts[0]) > 8:
            return False

        if len(parts[1]) < 1 or len(parts[1]) > 3:
            return False

        # If we have the openlocationcode library, use it for validation
        try:
            import openlocationcode as olc
            return olc.isValid(code)
        except ImportError:
            # Basic validation passed
            return True

    except Exception:
        return False


def get_shipment_location_data(shipment):
    """
    Get comprehensive location data for a shipment including Plus Code support

    Args:
        shipment: Shipment object

    Returns:
        dict: Location data with coordinates, address info, and geocoding details
    """
    address = shipment.shipping_address

    # Try to get coordinates using Plus Code or address
    location_data = geocode_address_with_plus_code(
        f"{address.street}, {address.city}, {address.region}",
        address.geo_code
    )

    result = {
        'shipment_id': shipment.id,
        'customer_name': address.full_name,
        'phone': address.phone_number,
        'address': {
            'street': address.street,
            'city': address.city,
            'region': address.region,
            'geo_code': address.geo_code,
            'full_address': f"{address.street}, {address.city}, {address.region}",
            'country': address.country
        },
        'shipment_details': {
            'weight_kg': shipment.weight_kg,
            'size_cubic_meters': shipment.size_cubic_meters,
            'material_type': shipment.get_material_type_display(),
            'shipment_type': shipment.get_shipment_type_display(),
            'status': shipment.status,
            'estimated_delivery': shipment.estimated_dropoff_time.isoformat() if shipment.estimated_dropoff_time else None
        }
    }

    # Add coordinates if geocoding was successful
    if location_data:
        result['coordinates'] = {
            'lat': location_data['lat'],
            'lng': location_data['lng'],
            'accuracy': location_data['accuracy'],
            'source': location_data['source']
        }

        # Generate Google Maps URLs
        result['maps_urls'] = {
            'directions': f"https://www.google.com/maps/dir/?api=1&destination={location_data['lat']},{location_data['lng']}",
            'view': f"https://www.google.com/maps?q={location_data['lat']},{location_data['lng']}",
            'plus_code_url': f"https://www.google.com/maps/search/{address.geo_code}" if address.geo_code else None
        }
    else:
        # Fallback to address-based URLs
        encoded_address = requests.utils.quote(f"{address.street}, {address.city}, {address.region}, Gambia")
        result['maps_urls'] = {
            'directions': f"https://www.google.com/maps/dir/?api=1&destination={encoded_address}",
            'view': f"https://www.google.com/maps/search/{encoded_address}",
            'plus_code_url': f"https://www.google.com/maps/search/{address.geo_code}" if address.geo_code else None
        }

    # Add Plus Code validation
    if address.geo_code:
        result['plus_code'] = {
            'code': address.geo_code,
            'is_valid': validate_plus_code(address.geo_code),
            'is_plus_code': '+' in address.geo_code
        }

    return result


# Additional utility functions for Plus Code integration

def generate_plus_code_from_coordinates(lat, lng):
    """
    Generate a Plus Code from latitude and longitude coordinates

    Args:
        lat (float): Latitude
        lng (float): Longitude

    Returns:
        str: Plus Code or None if failed
    """
    try:
        import openlocationcode as olc
        return olc.encode(lat, lng)
    except ImportError:
        print("openlocationcode library not installed")
        return None


def find_nearest_landmarks(lat, lng, radius_km=1):
    """
    Find nearby landmarks for a given coordinate (useful for delivery instructions)

    Args:
        lat (float): Latitude
        lng (float): Longitude
        radius_km (float): Search radius in kilometers

    Returns:
        list: List of nearby landmarks
    """
    try:
        # Using Overpass API to find nearby landmarks
        overpass_url = "http://overpass-api.de/api/interpreter"
        overpass_query = f"""
        [out:json][timeout:25];
        (
          node["amenity"~"school|hospital|mosque|market|bank"]
          (around:{radius_km * 1000},{lat},{lng});
          node["shop"]
          (around:{radius_km * 1000},{lat},{lng});
        );
        out body;
        """

        response = requests.get(overpass_url, params={'data': overpass_query})
        data = response.json()

        landmarks = []
        for element in data.get('elements', []):
            if 'tags' in element:
                name = element['tags'].get('name', 'Unnamed')
                amenity = element['tags'].get('amenity', element['tags'].get('shop', 'landmark'))

                landmarks.append({
                    'name': name,
                    'type': amenity,
                    'lat': element['lat'],
                    'lon': element['lon']
                })

        return landmarks[:5]  # Return top 5 landmarks

    except Exception as e:
        print(f"Error finding landmarks: {e}")
        return []


def enhance_delivery_instructions(shipment):
    """
    Generate enhanced delivery instructions using Plus Code and landmarks

    Args:
        shipment: Shipment object

    Returns:
        dict: Enhanced delivery instructions
    """
    location_data = get_shipment_location_data(shipment)

    instructions = {
        'primary_address': shipment.shipping_address.street,
        'plus_code': shipment.shipping_address.geo_code,
        'customer_phone': shipment.shipping_address.phone_number,
        'special_instructions': []
    }

    # Add Plus Code instructions
    if shipment.shipping_address.geo_code and validate_plus_code(shipment.shipping_address.geo_code):
        instructions['special_instructions'].append(
            f"Use Plus Code {shipment.shipping_address.geo_code} for precise navigation"
        )

    # Add landmark information if coordinates are available
    if 'coordinates' in location_data:
        landmarks = find_nearest_landmarks(
            location_data['coordinates']['lat'],
            location_data['coordinates']['lng']
        )

        if landmarks:
            landmark_text = "Nearby landmarks: " + ", ".join([
                f"{landmark['name']} ({landmark['type']})"
                for landmark in landmarks[:3]
            ])
            instructions['special_instructions'].append(landmark_text)

    return instructions

def create_exchange_shipment(ret):
    """
    Create a shipment for exchange items from store warehouse to buyer.
    """
    # Minimal example; adapt to your Shipment model fields.
    sh = Shipment.objects.create(
        origin_warehouse=None,  # set properly
        destination_address=ret.order.shipping_address,
        shipment_type='exchange',
        status='in_transit',
        created_at=timezone.now(),
        related_return=ret,  # add a FK in Shipment if useful
    )
    return sh