"""
Geocoding utilities for warehouse location management.

This module provides functions to geocode warehouse addresses and calculate
distances between warehouses.
"""

from decimal import Decimal
from typing import Optional, Tuple, Dict
import math


def geocode_address(address: str, city: str = '', state: str = '', 
                    country: str = '', postal_code: str = '') -> Optional[Tuple[Decimal, Decimal]]:
    """
    Geocode an address to get latitude and longitude coordinates.
    
    Note: This is a placeholder. In production, integrate with a geocoding service:
    - Google Maps Geocoding API
    - OpenStreetMap Nominatim
    - Mapbox Geocoding API
    - HERE Geocoding API
    
    Args:
        address: Street address
        city: City name
        state: State/province
        country: Country name
        postal_code: Postal/ZIP code
    
    Returns:
        Tuple of (latitude, longitude) or None if geocoding fails
    
    Example:
        lat, lon = geocode_address(
            address="1600 Amphitheatre Parkway",
            city="Mountain View",
            state="CA",
            country="USA",
            postal_code="94043"
        )
    """
    # Placeholder - Replace with actual geocoding service
    # Example using geopy with Nominatim:
    """
    from geopy.geocoders import Nominatim
    
    geolocator = Nominatim(user_agent="stock_management")
    full_address = f"{address}, {city}, {state} {postal_code}, {country}"
    
    try:
        location = geolocator.geocode(full_address)
        if location:
            return (Decimal(str(location.latitude)), Decimal(str(location.longitude)))
    except Exception as e:
        print(f"Geocoding error: {e}")
    
    return None
    """
    
    # For now, return None - you should implement actual geocoding
    return None


def reverse_geocode(latitude: float, longitude: float) -> Optional[Dict[str, str]]:
    """
    Reverse geocode coordinates to get address information.
    
    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate
    
    Returns:
        Dictionary with address components or None if reverse geocoding fails
        {
            'address': '1600 Amphitheatre Parkway',
            'city': 'Mountain View',
            'state': 'CA',
            'country': 'USA',
            'postal_code': '94043'
        }
    
    Example using geopy:
        from geopy.geocoders import Nominatim
        
        geolocator = Nominatim(user_agent="stock_management")
        location = geolocator.reverse(f"{latitude}, {longitude}")
        
        if location:
            address = location.raw.get('address', {})
            return {
                'address': address.get('road', ''),
                'city': address.get('city', ''),
                'state': address.get('state', ''),
                'country': address.get('country', ''),
                'postal_code': address.get('postcode', '')
            }
    """
    return None


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float, 
                      unit: str = 'km') -> float:
    """
    Calculate distance between two geographic coordinates using Haversine formula.
    
    Args:
        lat1: Latitude of first point
        lon1: Longitude of first point
        lat2: Latitude of second point
        lon2: Longitude of second point
        unit: 'km' for kilometers, 'mi' for miles, 'nm' for nautical miles
    
    Returns:
        Distance in specified unit
    
    Example:
        distance = calculate_distance(37.7749, -122.4194, 34.0522, -118.2437)
        # Distance between San Francisco and Los Angeles in km
    """
    # Earth's radius
    radius = {
        'km': 6371.0,      # kilometers
        'mi': 3958.8,      # miles
        'nm': 3440.1       # nautical miles
    }
    
    if unit not in radius:
        raise ValueError("Unit must be 'km', 'mi', or 'nm'")
    
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    # Haversine formula
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    distance = radius[unit] * c
    return round(distance, 2)


def find_nearest_warehouse(from_warehouse, warehouses_queryset):
    """
    Find the nearest warehouse from a queryset of warehouses.
    
    Args:
        from_warehouse: Warehouse model instance with geocode
        warehouses_queryset: QuerySet of Warehouse objects
    
    Returns:
        Tuple of (nearest_warehouse, distance_km) or (None, None) if no geocoded warehouses
    
    Example:
        from stock.models import Warehouse
        
        source = Warehouse.objects.get(code='WH01')
        all_warehouses = Warehouse.objects.exclude(id=source.id).filter(is_active=True)
        
        nearest, distance = find_nearest_warehouse(source, all_warehouses)
        if nearest:
            print(f"Nearest warehouse: {nearest.name} ({distance} km away)")
    """
    if not from_warehouse.has_geocode:
        return None, None
    
    lat1, lon1 = from_warehouse.get_coordinates()
    nearest = None
    min_distance = float('inf')
    
    for warehouse in warehouses_queryset:
        if warehouse.has_geocode and warehouse.id != from_warehouse.id:
            lat2, lon2 = warehouse.get_coordinates()
            distance = calculate_distance(lat1, lon1, lat2, lon2)
            
            if distance < min_distance:
                min_distance = distance
                nearest = warehouse
    
    if nearest:
        return nearest, min_distance
    
    return None, None


def get_warehouses_within_radius(center_warehouse, radius_km, warehouses_queryset):
    """
    Get all warehouses within a specified radius from a center warehouse.
    
    Args:
        center_warehouse: Warehouse model instance with geocode
        radius_km: Radius in kilometers
        warehouses_queryset: QuerySet of Warehouse objects
    
    Returns:
        List of tuples (warehouse, distance_km) sorted by distance
    
    Example:
        from stock.models import Warehouse
        
        center = Warehouse.objects.get(code='WH01')
        all_warehouses = Warehouse.objects.filter(is_active=True)
        
        nearby = get_warehouses_within_radius(center, 100, all_warehouses)
        for warehouse, distance in nearby:
            print(f"{warehouse.name}: {distance} km away")
    """
    if not center_warehouse.has_geocode:
        return []
    
    lat1, lon1 = center_warehouse.get_coordinates()
    results = []
    
    for warehouse in warehouses_queryset:
        if warehouse.has_geocode and warehouse.id != center_warehouse.id:
            lat2, lon2 = warehouse.get_coordinates()
            distance = calculate_distance(lat1, lon1, lat2, lon2)
            
            if distance <= radius_km:
                results.append((warehouse, distance))
    
    # Sort by distance
    results.sort(key=lambda x: x[1])
    return results


def update_warehouse_geocode(warehouse, geocoding_service='manual'):
    """
    Update warehouse geocode based on its address.
    
    Args:
        warehouse: Warehouse model instance
        geocoding_service: 'manual', 'google', 'nominatim', etc.
    
    Returns:
        Boolean indicating success
    
    Example:
        from stock.models import Warehouse
        
        warehouse = Warehouse.objects.get(code='WH01')
        success = update_warehouse_geocode(warehouse, geocoding_service='nominatim')
    """
    if geocoding_service == 'manual':
        # Manual geocoding - return False to indicate no action taken
        return False
    
    # Placeholder for actual geocoding service integration
    coordinates = geocode_address(
        address=warehouse.address,
        city=warehouse.city,
        state=warehouse.state,
        country=warehouse.country,
        postal_code=warehouse.postal_code
    )
    
    if coordinates:
        warehouse.latitude, warehouse.longitude = coordinates
        warehouse.save()
        return True
    
    return False


def get_warehouse_distance_matrix(warehouses_queryset):
    """
    Calculate distance matrix between all warehouses.
    
    Args:
        warehouses_queryset: QuerySet of Warehouse objects with geocodes
    
    Returns:
        Dictionary with warehouse pairs as keys and distances as values
        {
            ('WH01', 'WH02'): 150.5,
            ('WH01', 'WH03'): 320.8,
            ...
        }
    
    Example:
        from stock.models import Warehouse
        
        warehouses = Warehouse.objects.filter(is_active=True)
        matrix = get_warehouse_distance_matrix(warehouses)
        
        distance = matrix.get(('WH01', 'WH02'), 'N/A')
        print(f"Distance between WH01 and WH02: {distance} km")
    """
    warehouses = [w for w in warehouses_queryset if w.has_geocode]
    matrix = {}
    
    for i, wh1 in enumerate(warehouses):
        for wh2 in warehouses[i+1:]:
            lat1, lon1 = wh1.get_coordinates()
            lat2, lon2 = wh2.get_coordinates()
            distance = calculate_distance(lat1, lon1, lat2, lon2)
            
            # Store both directions
            matrix[(wh1.code, wh2.code)] = distance
            matrix[(wh2.code, wh1.code)] = distance
    
    return matrix


def suggest_optimal_transfer_route(product, target_warehouse, max_hops=2):
    """
    Suggest optimal warehouse transfer route based on stock availability and distance.
    
    Args:
        product: Product instance
        target_warehouse: Destination warehouse
        max_hops: Maximum number of transfer hops
    
    Returns:
        List of warehouse codes representing the transfer route
    
    Example:
        route = suggest_optimal_transfer_route(product, target_warehouse, max_hops=2)
        # Returns: ['WH03', 'WH01', 'WH02'] meaning transfer from WH03 -> WH01 -> WH02
    """
    from stock.models import Stock
    
    # Get all warehouses with stock for this product
    available_stocks = Stock.objects.filter(
        product=product,
        quantity__gt=0,
        warehouse__is_active=True
    ).select_related('warehouse').exclude(
        warehouse=target_warehouse
    )
    
    if not target_warehouse.has_geocode:
        # If target doesn't have geocode, return closest warehouse with stock
        if available_stocks.exists():
            return [available_stocks.first().warehouse.code, target_warehouse.code]
        return []
    
    # Find nearest warehouse with stock
    target_lat, target_lon = target_warehouse.get_coordinates()
    nearest = None
    min_distance = float('inf')
    
    for stock in available_stocks:
        if stock.warehouse.has_geocode:
            lat, lon = stock.warehouse.get_coordinates()
            distance = calculate_distance(target_lat, target_lon, lat, lon)
            
            if distance < min_distance:
                min_distance = distance
                nearest = stock.warehouse
    
    if nearest:
        return [nearest.code, target_warehouse.code]
    
    return []


# Integration example with Google Maps Geocoding API
"""
To use Google Maps Geocoding API:

1. Install googlemaps:
   pip install googlemaps

2. Get API key from Google Cloud Console

3. Use this function:

import googlemaps

def geocode_with_google(address, city='', state='', country='', postal_code='', api_key='YOUR_API_KEY'):
    gmaps = googlemaps.Client(key=api_key)
    
    full_address = f"{address}, {city}, {state} {postal_code}, {country}"
    
    try:
        result = gmaps.geocode(full_address)
        if result:
            location = result[0]['geometry']['location']
            return (Decimal(str(location['lat'])), Decimal(str(location['lng'])))
    except Exception as e:
        print(f"Google geocoding error: {e}")
    
    return None
"""

# Integration example with OpenStreetMap Nominatim
"""
To use Nominatim:

1. Install geopy:
   pip install geopy

2. Use this function:

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

def geocode_with_nominatim(address, city='', state='', country='', postal_code=''):
    geolocator = Nominatim(user_agent="stock_management_system")
    
    full_address = f"{address}, {city}, {state} {postal_code}, {country}"
    
    try:
        location = geolocator.geocode(full_address, timeout=10)
        if location:
            return (Decimal(str(location.latitude)), Decimal(str(location.longitude)))
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"Nominatim geocoding error: {e}")
    
    return None
"""
