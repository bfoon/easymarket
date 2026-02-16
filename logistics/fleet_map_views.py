from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.db.models import Count, Q, Sum
from django.utils import timezone
from datetime import timedelta
from .models import (
    Order, LogisticsLocation, DeliveryRoute, DeliveryStop, 
    VehicleTracking, FleetVehicle
)
from stores.models import Store
from decimal import Decimal
import json


def is_staff_or_logistics(user):
    """Check if user is staff or in logistics team"""
    return user.is_staff or user.groups.filter(name__in=['Logistics', 'Fleet Management']).exists()


@login_required
@user_passes_test(is_staff_or_logistics)
def fleet_map_view(request):
    """
    Main fleet management map view
    """
    context = {
        'page_title': 'Fleet Management Map',
        'active_routes_count': DeliveryRoute.objects.filter(status='in_progress').count(),
        'pending_deliveries': DeliveryStop.objects.filter(status='pending').count(),
        'active_vehicles': FleetVehicle.objects.filter(status='active').count(),
    }
    return render(request, 'logistics/fleet_map.html', context)


@login_required
@user_passes_test(is_staff_or_logistics)
def fleet_map_data(request):
    """
    API endpoint to get all map data
    Returns JSON with locations, routes, vehicles, and statistics
    """
    try:
        # Get filter parameters
        status_filter = request.GET.get('status', 'all')
        route_filter = request.GET.get('route', 'all')
        time_filter = request.GET.get('time', 'today')
        
        # Calculate time range
        now = timezone.now()
        if time_filter == 'today':
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif time_filter == 'week':
            start_time = now - timedelta(days=7)
        elif time_filter == 'month':
            start_time = now - timedelta(days=30)
        else:
            start_time = now - timedelta(days=1)
        
        # Get all logistics locations
        locations = []
        
        # 1. STORES
        stores = LogisticsLocation.objects.filter(
            location_type='store',
            is_active=True
        ).select_related('store')
        
        for loc in stores:
            # Count pending pickups from this store
            pending_pickups = DeliveryStop.objects.filter(
                location=loc,
                stop_type='pickup',
                status__in=['pending', 'arrived']
            ).count()
            
            # Get orders from this store
            store_orders = Order.objects.filter(
                items__product__seller__store=loc.store,
                created_at__gte=start_time
            ).distinct()
            
            locations.append({
                'id': loc.id,
                'name': loc.name,
                'type': 'store',
                'lat': float(loc.latitude),
                'lng': float(loc.longitude),
                'address': loc.address,
                'contact': loc.contact_person,
                'phone': loc.contact_phone,
                'stats': {
                    'pending_pickups': pending_pickups,
                    'total_orders': store_orders.count(),
                },
                'icon': 'store',
                'color': '#3b82f6'  # Blue
            })
        
        # 2. WAREHOUSES
        warehouses = LogisticsLocation.objects.filter(
            location_type='warehouse',
            is_active=True
        )
        
        for loc in warehouses:
            locations.append({
                'id': loc.id,
                'name': loc.name,
                'type': 'warehouse',
                'lat': float(loc.latitude),
                'lng': float(loc.longitude),
                'address': loc.address,
                'contact': loc.contact_person,
                'phone': loc.contact_phone,
                'stats': {},
                'icon': 'warehouse',
                'color': '#8b5cf6'  # Purple
            })
        
        # 3. DELIVERY STOPS (Active deliveries)
        delivery_stops = DeliveryStop.objects.filter(
            created_at__gte=start_time,
            status__in=['pending', 'arrived', 'in_progress']
        ).select_related('route', 'order')
        
        if route_filter != 'all':
            delivery_stops = delivery_stops.filter(route_id=route_filter)
        
        for stop in delivery_stops:
            # Get tracking numbers
            tracking_nums = stop.tracking_numbers if stop.tracking_numbers else []
            if stop.order:
                tracking_nums.append(stop.order.tracking_number)
            
            locations.append({
                'id': f"stop_{stop.id}",
                'name': stop.contact_name,
                'type': stop.stop_type,
                'lat': float(stop.latitude),
                'lng': float(stop.longitude),
                'address': stop.address,
                'contact': stop.contact_name,
                'phone': stop.contact_phone,
                'stats': {
                    'packages': stop.packages_count,
                    'tracking_numbers': tracking_nums,
                    'sequence': stop.sequence_number,
                    'status': stop.get_status_display(),
                    'route': stop.route.route_number if stop.route else None,
                },
                'icon': 'delivery' if stop.stop_type == 'delivery' else 'pickup',
                'color': '#10b981' if stop.stop_type == 'delivery' else '#f59e0b',  # Green or Orange
                'status': stop.status
            })
        
        # Get active routes
        routes_query = DeliveryRoute.objects.filter(
            created_at__gte=start_time
        ).select_related('driver', 'start_location')
        
        if status_filter != 'all':
            routes_query = routes_query.filter(status=status_filter)
        
        if route_filter != 'all':
            routes_query = routes_query.filter(id=route_filter)
        
        routes = []
        for route in routes_query:
            # Get route stops
            stops = list(route.stops.order_by('sequence_number').values(
                'id', 'latitude', 'longitude', 'sequence_number', 
                'status', 'stop_type', 'address'
            ))
            
            # Get latest vehicle tracking
            latest_tracking = VehicleTracking.objects.filter(
                route=route
            ).order_by('-timestamp').first()
            
            route_data = {
                'id': route.id,
                'route_number': route.route_number,
                'status': route.status,
                'status_display': route.get_status_display(),
                'driver': route.driver.get_full_name() if route.driver else 'Unassigned',
                'vehicle': route.vehicle,
                'total_stops': route.total_stops,
                'completed_stops': route.completed_stops,
                'progress': route.progress_percentage,
                'stops': stops,
            }
            
            # Add current vehicle location if available
            if latest_tracking:
                route_data['current_location'] = {
                    'lat': float(latest_tracking.latitude),
                    'lng': float(latest_tracking.longitude),
                    'speed': float(latest_tracking.speed_kmh),
                    'heading': latest_tracking.heading,
                    'timestamp': latest_tracking.timestamp.isoformat(),
                }
            
            routes.append(route_data)
        
        # Get active vehicles with current locations
        vehicles = []
        active_vehicles = FleetVehicle.objects.filter(status='active')
        
        for vehicle in active_vehicles:
            if vehicle.current_latitude and vehicle.current_longitude:
                # Find if vehicle is on an active route
                active_route = DeliveryRoute.objects.filter(
                    vehicle=vehicle.vehicle_number,
                    status='in_progress'
                ).first()
                
                vehicles.append({
                    'id': vehicle.id,
                    'vehicle_number': vehicle.vehicle_number,
                    'license_plate': vehicle.license_plate,
                    'type': vehicle.get_vehicle_type_display(),
                    'driver': vehicle.current_driver.get_full_name() if vehicle.current_driver else 'None',
                    'lat': float(vehicle.current_latitude),
                    'lng': float(vehicle.current_longitude),
                    'last_update': vehicle.last_location_update.isoformat() if vehicle.last_location_update else None,
                    'on_route': active_route.route_number if active_route else None,
                })
        
        # Calculate statistics
        stats = {
            'total_locations': len(locations),
            'active_routes': routes_query.filter(status='in_progress').count(),
            'completed_today': routes_query.filter(
                status='completed',
                actual_end_time__gte=start_time
            ).count(),
            'pending_deliveries': delivery_stops.filter(status='pending').count(),
            'in_progress_deliveries': delivery_stops.filter(status__in=['arrived', 'in_progress']).count(),
            'completed_deliveries': DeliveryStop.objects.filter(
                status='completed',
                completed_at__gte=start_time
            ).count(),
            'failed_deliveries': delivery_stops.filter(status='failed').count(),
            'active_vehicles': len(vehicles),
            'total_packages': sum(stop.packages_count for stop in delivery_stops),
        }
        
        # Summary by type
        location_summary = {
            'stores': sum(1 for loc in locations if loc['type'] == 'store'),
            'warehouses': sum(1 for loc in locations if loc['type'] == 'warehouse'),
            'deliveries': sum(1 for loc in locations if loc['type'] == 'delivery'),
            'pickups': sum(1 for loc in locations if loc['type'] == 'pickup'),
        }
        
        return JsonResponse({
            'success': True,
            'locations': locations,
            'routes': routes,
            'vehicles': vehicles,
            'stats': stats,
            'location_summary': location_summary,
            'timestamp': now.isoformat(),
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_staff_or_logistics)
def route_detail_api(request, route_id):
    """
    Get detailed information about a specific route
    """
    try:
        route = DeliveryRoute.objects.get(id=route_id)
        
        # Get all stops with details
        stops = []
        for stop in route.stops.order_by('sequence_number'):
            stops.append({
                'id': stop.id,
                'sequence': stop.sequence_number,
                'type': stop.get_stop_type_display(),
                'status': stop.get_status_display(),
                'address': stop.address,
                'contact': stop.contact_name,
                'phone': stop.contact_phone,
                'packages': stop.packages_count,
                'tracking_numbers': stop.tracking_numbers,
                'lat': float(stop.latitude),
                'lng': float(stop.longitude),
                'planned_arrival': stop.planned_arrival.isoformat() if stop.planned_arrival else None,
                'actual_arrival': stop.actual_arrival.isoformat() if stop.actual_arrival else None,
                'completed_at': stop.completed_at.isoformat() if stop.completed_at else None,
                'notes': stop.notes,
            })
        
        # Get tracking history
        tracking_points = []
        for point in route.tracking_points.order_by('-timestamp')[:100]:
            tracking_points.append({
                'lat': float(point.latitude),
                'lng': float(point.longitude),
                'speed': float(point.speed_kmh),
                'timestamp': point.timestamp.isoformat(),
            })
        
        data = {
            'success': True,
            'route': {
                'id': route.id,
                'route_number': route.route_number,
                'status': route.get_status_display(),
                'driver': route.driver.get_full_name() if route.driver else 'Unassigned',
                'vehicle': route.vehicle,
                'total_stops': route.total_stops,
                'completed_stops': route.completed_stops,
                'progress': route.progress_percentage,
                'total_distance': float(route.total_distance_km),
                'planned_start': route.planned_start_time.isoformat(),
                'actual_start': route.actual_start_time.isoformat() if route.actual_start_time else None,
                'estimated_end': route.estimated_end_time.isoformat() if route.estimated_end_time else None,
                'notes': route.notes,
            },
            'stops': stops,
            'tracking_history': tracking_points,
        }
        
        return JsonResponse(data)
        
    except DeliveryRoute.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Route not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_staff_or_logistics)
def update_vehicle_location(request):
    """
    API endpoint to update vehicle location (for mobile apps)
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            route_id = data.get('route_id')
            latitude = data.get('latitude')
            longitude = data.get('longitude')
            speed = data.get('speed', 0)
            heading = data.get('heading')
            accuracy = data.get('accuracy', 0)
            
            route = DeliveryRoute.objects.get(id=route_id)
            
            # Create tracking point
            VehicleTracking.objects.create(
                route=route,
                latitude=latitude,
                longitude=longitude,
                speed_kmh=speed,
                heading=heading,
                accuracy_meters=accuracy,
            )
            
            # Update vehicle current location
            if route.driver and hasattr(route.driver, 'current_vehicle'):
                vehicle = route.driver.current_vehicle
                if vehicle:
                    vehicle.current_latitude = latitude
                    vehicle.current_longitude = longitude
                    vehicle.last_location_update = timezone.now()
                    vehicle.save()
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
    
    return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
