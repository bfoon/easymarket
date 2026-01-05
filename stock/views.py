from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta
from decimal import Decimal
import json

from .models import (
    Stock, Warehouse, StockMovement, StockReservation,
    StockCount, StockAlert, BatchTracking, PurchaseOrder
)
from .utils import (
    adjust_stock, transfer_stock, reserve_stock, release_reservation,
    fulfill_reservation, get_reorder_suggestions, check_expiring_batches,
    calculate_stock_turnover, calculate_days_of_stock, get_stock_valuation_report,
    get_movement_summary, get_slow_moving_products, get_fast_moving_products,
    perform_abc_analysis, receive_purchase_order, complete_stock_count,
    generate_daily_analytics
)


# ==================== STOCK MANAGEMENT ENDPOINTS ====================

@require_POST
@csrf_exempt
def adjust_stock_view(request):
    """Adjust stock levels with full audit trail"""
    try:
        data = json.loads(request.body)

        stock, movement = adjust_stock(
            product_id=data['product_id'],
            warehouse_id=data['warehouse_id'],
            quantity=int(data['quantity']),
            movement_type=data['movement_type'],
            user=request.user if request.user.is_authenticated else None,
            reference_number=data.get('reference_number', ''),
            unit_cost=Decimal(data.get('unit_cost', '0.00')),
            notes=data.get('notes', '')
        )

        return JsonResponse({
            'success': True,
            'stock': {
                'id': stock.id,
                'quantity': stock.quantity,
                'available_quantity': stock.available_quantity,
                'reserved_quantity': stock.reserved_quantity
            },
            'movement': {
                'id': movement.id,
                'type': movement.movement_type,
                'quantity': movement.quantity,
                'reference': movement.reference_number
            }
        })

    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
@csrf_exempt
def transfer_stock_view(request):
    """Transfer stock between warehouses"""
    try:
        data = json.loads(request.body)

        (stock_out, stock_in), (movement_out, movement_in) = transfer_stock(
            product_id=data['product_id'],
            from_warehouse_id=data['from_warehouse_id'],
            to_warehouse_id=data['to_warehouse_id'],
            quantity=int(data['quantity']),
            user=request.user if request.user.is_authenticated else None,
            notes=data.get('notes', '')
        )

        return JsonResponse({
            'success': True,
            'from_warehouse': {
                'stock_id': stock_out.id,
                'quantity': stock_out.quantity,
                'movement_id': movement_out.id
            },
            'to_warehouse': {
                'stock_id': stock_in.id,
                'quantity': stock_in.quantity,
                'movement_id': movement_in.id
            }
        })

    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_GET
def stock_status(request, product_id):
    """Get current stock status across all warehouses"""
    try:
        stocks = Stock.objects.filter(product_id=product_id).select_related('warehouse')

        stock_data = []
        total_quantity = 0
        total_available = 0
        total_reserved = 0

        for stock in stocks:
            stock_data.append({
                'warehouse': {
                    'id': stock.warehouse.id,
                    'code': stock.warehouse.code,
                    'name': stock.warehouse.name
                },
                'quantity': stock.quantity,
                'available': stock.available_quantity,
                'reserved': stock.reserved_quantity,
                'reorder_level': stock.reorder_level,
                'needs_reorder': stock.is_below_reorder_level,
                'unit_cost': float(stock.unit_cost),
                'stock_value': float(stock.stock_value),
                'updated_at': stock.updated_at.isoformat()
            })

            total_quantity += stock.quantity
            total_available += stock.available_quantity
            total_reserved += stock.reserved_quantity

        return JsonResponse({
            'success': True,
            'product_id': product_id,
            'summary': {
                'total_quantity': total_quantity,
                'total_available': total_available,
                'total_reserved': total_reserved
            },
            'warehouses': stock_data
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== RESERVATION ENDPOINTS ====================

@require_POST
@csrf_exempt
def create_reservation(request):
    """Create a stock reservation"""
    try:
        data = json.loads(request.body)

        reservation = reserve_stock(
            product_id=data['product_id'],
            warehouse_id=data['warehouse_id'],
            quantity=int(data['quantity']),
            order_reference=data['order_reference'],
            user=request.user if request.user.is_authenticated else None,
            hours_valid=int(data.get('hours_valid', 24))
        )

        return JsonResponse({
            'success': True,
            'reservation': {
                'id': reservation.id,
                'quantity': reservation.quantity,
                'order_reference': reservation.order_reference,
                'expires_at': reservation.expires_at.isoformat(),
                'is_active': reservation.is_active
            }
        })

    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
@csrf_exempt
def release_reservation_view(request, reservation_id):
    """Release a stock reservation"""
    try:
        reservation = StockReservation.objects.get(id=reservation_id)
        success = release_reservation(reservation)

        return JsonResponse({
            'success': success,
            'reservation_id': reservation_id,
            'released': success
        })

    except StockReservation.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Reservation not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
@csrf_exempt
def fulfill_reservation_view(request, reservation_id):
    """Fulfill a reservation by dispatching stock"""
    try:
        reservation = StockReservation.objects.get(id=reservation_id)
        success = fulfill_reservation(
            reservation,
            user=request.user if request.user.is_authenticated else None
        )

        return JsonResponse({
            'success': success,
            'reservation_id': reservation_id,
            'fulfilled': success
        })

    except StockReservation.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Reservation not found'}, status=404)
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== ALERTS & MONITORING ====================

@require_GET
def active_alerts(request):
    """Get all active stock alerts"""
    try:
        warehouse_id = request.GET.get('warehouse_id')
        alert_type = request.GET.get('alert_type')

        alerts = StockAlert.objects.filter(status='ACTIVE').select_related(
            'stock__product', 'stock__warehouse'
        )

        if warehouse_id:
            alerts = alerts.filter(stock__warehouse_id=warehouse_id)

        if alert_type:
            alerts = alerts.filter(alert_type=alert_type)

        alerts_data = []
        for alert in alerts:
            alerts_data.append({
                'id': alert.id,
                'type': alert.alert_type,
                'type_display': alert.get_alert_type_display(),
                'product': {
                    'id': alert.stock.product.id,
                    'name': alert.stock.product.name
                },
                'warehouse': {
                    'id': alert.stock.warehouse.id,
                    'code': alert.stock.warehouse.code
                },
                'message': alert.message,
                'created_at': alert.created_at.isoformat()
            })

        return JsonResponse({
            'success': True,
            'count': len(alerts_data),
            'alerts': alerts_data
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_GET
def reorder_suggestions_view(request):
    """Get products that need reordering"""
    try:
        suggestions = get_reorder_suggestions()

        suggestions_data = []
        for item in suggestions:
            suggestions_data.append({
                'product': {
                    'id': item['product'].id,
                    'name': item['product'].name
                },
                'warehouse': {
                    'id': item['warehouse'].id,
                    'code': item['warehouse'].code
                },
                'current_quantity': item['current_quantity'],
                'reorder_level': item['reorder_level'],
                'suggested_quantity': item['suggested_quantity'],
                'unit_cost': float(item['unit_cost']),
                'estimated_cost': float(item['estimated_cost'])
            })

        return JsonResponse({
            'success': True,
            'count': len(suggestions_data),
            'suggestions': suggestions_data,
            'total_estimated_cost': sum(s['estimated_cost'] for s in suggestions_data)
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_GET
def expiring_batches_view(request):
    """Get batches expiring soon"""
    try:
        days_ahead = int(request.GET.get('days', 30))
        batches = check_expiring_batches(days_ahead)

        batches_data = []
        for batch in batches:
            batches_data.append({
                'batch_number': batch.batch_number,
                'product': {
                    'id': batch.product.id,
                    'name': batch.product.name
                },
                'warehouse': {
                    'id': batch.warehouse.id,
                    'code': batch.warehouse.code
                },
                'quantity': batch.quantity,
                'expiry_date': batch.expiry_date.isoformat(),
                'days_until_expiry': batch.days_until_expiry,
                'is_expired': batch.is_expired
            })

        return JsonResponse({
            'success': True,
            'count': len(batches_data),
            'batches': batches_data
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== ANALYTICS & REPORTS ====================

@require_GET
def stock_valuation_report(request):
    """Get stock valuation report"""
    try:
        warehouse_id = request.GET.get('warehouse_id')
        warehouse = Warehouse.objects.get(id=warehouse_id) if warehouse_id else None

        report = get_stock_valuation_report(warehouse)

        return JsonResponse({
            'success': True,
            'report': {
                'total_value': float(report['total_value']),
                'total_quantity': report['total_quantity'],
                'stock_count': report['stock_count'],
                'by_warehouse': [
                    {
                        'warehouse_name': w['warehouse__name'],
                        'warehouse_code': w['warehouse__code'],
                        'total_value': float(w['total_value']),
                        'total_items': w['total_items'],
                        'product_count': w['product_count']
                    }
                    for w in report['by_warehouse']
                ]
            }
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_GET
def movement_report(request):
    """Get stock movement summary for a period"""
    try:
        start_date = datetime.strptime(request.GET.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.GET.get('end_date'), '%Y-%m-%d').date()
        warehouse_id = request.GET.get('warehouse_id')
        movement_type = request.GET.get('movement_type')

        warehouse = Warehouse.objects.get(id=warehouse_id) if warehouse_id else None

        summary = get_movement_summary(start_date, end_date, warehouse, movement_type)

        return JsonResponse({
            'success': True,
            'period': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': [
                {
                    'movement_type': item['movement_type'],
                    'total_quantity': item['total_quantity'],
                    'total_value': float(item['total_value']),
                    'count': item['count']
                }
                for item in summary
            ]
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_GET
def product_analytics(request, product_id):
    """Get analytics for a specific product"""
    try:
        warehouse_id = request.GET.get('warehouse_id')
        days = int(request.GET.get('days', 30))

        from marketplace.models import Product
        product = Product.objects.get(id=product_id)
        warehouse = Warehouse.objects.get(id=warehouse_id) if warehouse_id else None

        turnover = calculate_stock_turnover(product, warehouse, days)
        days_stock = calculate_days_of_stock(product, warehouse, days)

        return JsonResponse({
            'success': True,
            'product_id': product_id,
            'analytics': {
                'turnover_rate': float(turnover),
                'days_of_stock': float(days_stock) if days_stock != float('inf') else None,
                'period_days': days
            }
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_GET
def slow_moving_products_view(request):
    """Get slow-moving products report"""
    try:
        days = int(request.GET.get('days', 90))
        threshold = int(request.GET.get('threshold', 5))

        products = get_slow_moving_products(days, threshold)

        products_data = []
        for item in products:
            products_data.append({
                'product': {
                    'id': item['product'].id,
                    'name': item['product'].name
                },
                'warehouse': {
                    'id': item['warehouse'].id,
                    'code': item['warehouse'].code
                },
                'current_stock': item['current_stock'],
                'units_sold': item['units_sold'],
                'stock_value': float(item['stock_value']),
                'days_analyzed': item['days_analyzed']
            })

        return JsonResponse({
            'success': True,
            'count': len(products_data),
            'products': products_data,
            'total_value_tied_up': sum(p['stock_value'] for p in products_data)
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_GET
def fast_moving_products_view(request):
    """Get fast-moving products report"""
    try:
        days = int(request.GET.get('days', 30))
        min_sales = int(request.GET.get('min_sales', 50))

        products = get_fast_moving_products(days, min_sales)

        products_data = []
        for item in products:
            products_data.append({
                'product': {
                    'id': item['product'].id,
                    'name': item['product'].name
                },
                'warehouse': {
                    'id': item['warehouse'].id,
                    'code': item['warehouse'].code
                },
                'current_stock': item['current_stock'],
                'units_sold': item['units_sold'],
                'turnover_rate': float(item['turnover_rate']),
                'days_analyzed': item['days_analyzed']
            })

        return JsonResponse({
            'success': True,
            'count': len(products_data),
            'products': products_data
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_GET
def abc_analysis_view(request):
    """Get ABC analysis of inventory"""
    try:
        warehouse_id = request.GET.get('warehouse_id')
        warehouse = Warehouse.objects.get(id=warehouse_id) if warehouse_id else None

        analysis = perform_abc_analysis(warehouse)

        def format_category(items):
            return [
                {
                    'product': {
                        'id': item['product'].id,
                        'name': item['product'].name
                    },
                    'warehouse': {
                        'id': item['warehouse'].id,
                        'code': item['warehouse'].code
                    },
                    'quantity': item['quantity'],
                    'unit_cost': float(item['unit_cost']),
                    'total_value': float(item['total_value']),
                    'cumulative_percentage': item['cumulative_percentage']
                }
                for item in items
            ]

        return JsonResponse({
            'success': True,
            'analysis': {
                'A': {
                    'count': len(analysis['A']),
                    'items': format_category(analysis['A'])
                },
                'B': {
                    'count': len(analysis['B']),
                    'items': format_category(analysis['B'])
                },
                'C': {
                    'count': len(analysis['C']),
                    'items': format_category(analysis['C'])
                }
            }
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== PURCHASE ORDER ENDPOINTS ====================

@require_POST
@csrf_exempt
def receive_po_view(request, po_id):
    """Receive items from a purchase order"""
    try:
        data = json.loads(request.body)

        result = receive_purchase_order(
            po_id=po_id,
            items_received=data['items'],
            user=request.user if request.user.is_authenticated else None
        )

        return JsonResponse({
            'success': True,
            'po_number': result['po'].po_number,
            'status': result['po'].status,
            'fully_received': result['fully_received'],
            'items_received': [
                {
                    'product_id': item['product'].id,
                    'product_name': item['product'].name,
                    'quantity': item['quantity'],
                    'stock_id': item['stock'].id
                }
                for item in result['items_received']
            ]
        })

    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== STOCK COUNT ENDPOINTS ====================

@require_POST
@csrf_exempt
def complete_count_view(request, count_id):
    """Complete a stock count and apply adjustments"""
    try:
        data = json.loads(request.body)
        auto_adjust = data.get('auto_adjust', True)

        stock_count = StockCount.objects.get(id=count_id)
        adjustments = complete_stock_count(stock_count, auto_adjust)

        return JsonResponse({
            'success': True,
            'count_id': count_id,
            'status': stock_count.status,
            'adjustments_count': len(adjustments),
            'adjustments': [
                {
                    'product_id': adj['product'].id,
                    'product_name': adj['product'].name,
                    'variance': adj['variance'],
                    'new_quantity': adj['stock'].quantity
                }
                for adj in adjustments
            ]
        })

    except StockCount.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Stock count not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== BATCH OPERATIONS ====================

@require_GET
def batch_info(request, batch_number):
    """Get information about a specific batch"""
    try:
        batches = BatchTracking.objects.filter(batch_number=batch_number).select_related(
            'product', 'warehouse'
        )

        batches_data = []
        for batch in batches:
            batches_data.append({
                'id': batch.id,
                'batch_number': batch.batch_number,
                'product': {
                    'id': batch.product.id,
                    'name': batch.product.name
                },
                'warehouse': {
                    'id': batch.warehouse.id,
                    'code': batch.warehouse.code
                },
                'quantity': batch.quantity,
                'manufacturing_date': batch.manufacturing_date.isoformat() if batch.manufacturing_date else None,
                'expiry_date': batch.expiry_date.isoformat() if batch.expiry_date else None,
                'days_until_expiry': batch.days_until_expiry,
                'is_expired': batch.is_expired,
                'supplier_reference': batch.supplier_reference,
                'received_date': batch.received_date.isoformat()
            })

        return JsonResponse({
            'success': True,
            'batch_number': batch_number,
            'count': len(batches_data),
            'batches': batches_data
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== WAREHOUSE GEOCODING & DISTANCE ====================

@require_GET
def warehouse_distances(request):
    """Get distances between warehouses"""
    try:
        from_code = request.GET.get('from')
        to_code = request.GET.get('to')

        if from_code and to_code:
            # Get distance between two specific warehouses
            from stock.geocoding_utils import calculate_distance

            from_wh = Warehouse.objects.get(code=from_code)
            to_wh = Warehouse.objects.get(code=to_code)

            if not from_wh.has_geocode or not to_wh.has_geocode:
                return JsonResponse({
                    'success': False,
                    'error': 'One or both warehouses do not have geocode coordinates'
                }, status=400)

            from_coords = from_wh.get_coordinates()
            to_coords = to_wh.get_coordinates()

            distance_km = calculate_distance(
                from_coords[0], from_coords[1],
                to_coords[0], to_coords[1],
                unit='km'
            )
            distance_mi = calculate_distance(
                from_coords[0], from_coords[1],
                to_coords[0], to_coords[1],
                unit='mi'
            )

            return JsonResponse({
                'success': True,
                'from': {
                    'code': from_wh.code,
                    'name': from_wh.name,
                    'coordinates': from_coords
                },
                'to': {
                    'code': to_wh.code,
                    'name': to_wh.name,
                    'coordinates': to_coords
                },
                'distance': {
                    'km': distance_km,
                    'miles': distance_mi
                }
            })

        else:
            # Get distance matrix for all warehouses
            from stock.geocoding_utils import get_warehouse_distance_matrix

            warehouses = Warehouse.objects.filter(is_active=True)
            matrix = get_warehouse_distance_matrix(warehouses)

            # Format matrix for response
            formatted_matrix = []
            for (from_code, to_code), distance in matrix.items():
                formatted_matrix.append({
                    'from': from_code,
                    'to': to_code,
                    'distance_km': distance
                })

            return JsonResponse({
                'success': True,
                'count': len(formatted_matrix),
                'distances': formatted_matrix
            })

    except Warehouse.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Warehouse not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_GET
def nearby_warehouses(request, warehouse_code):
    """Get warehouses within a specified radius"""
    try:
        from stock.geocoding_utils import get_warehouses_within_radius

        radius_km = float(request.GET.get('radius', 100))

        center = Warehouse.objects.get(code=warehouse_code)
        all_warehouses = Warehouse.objects.filter(is_active=True)

        nearby = get_warehouses_within_radius(center, radius_km, all_warehouses)

        warehouses_data = []
        for warehouse, distance in nearby:
            warehouses_data.append({
                'code': warehouse.code,
                'name': warehouse.name,
                'city': warehouse.city,
                'state': warehouse.state,
                'distance_km': distance,
                'coordinates': warehouse.get_coordinates()
            })

        return JsonResponse({
            'success': True,
            'center': {
                'code': center.code,
                'name': center.name
            },
            'radius_km': radius_km,
            'count': len(warehouses_data),
            'warehouses': warehouses_data
        })

    except Warehouse.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Warehouse not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_GET
def nearest_warehouse_view(request, warehouse_code):
    """Find nearest warehouse to a given warehouse"""
    try:
        from stock.geocoding_utils import find_nearest_warehouse

        source = Warehouse.objects.get(code=warehouse_code)
        other_warehouses = Warehouse.objects.filter(is_active=True).exclude(code=warehouse_code)

        nearest, distance = find_nearest_warehouse(source, other_warehouses)

        if nearest:
            return JsonResponse({
                'success': True,
                'source': {
                    'code': source.code,
                    'name': source.name
                },
                'nearest': {
                    'code': nearest.code,
                    'name': nearest.name,
                    'city': nearest.city,
                    'state': nearest.state,
                    'distance_km': distance,
                    'coordinates': nearest.get_coordinates()
                }
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'No nearby warehouses found with geocode'
            }, status=404)

    except Warehouse.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Warehouse not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== UTILITY ENDPOINTS ====================

@require_POST
@csrf_exempt
def generate_analytics_view(request):
    """Manually trigger analytics generation"""
    try:
        data = json.loads(request.body)
        target_date = datetime.strptime(data.get('date'), '%Y-%m-%d').date() if data.get('date') else None

        generate_daily_analytics(target_date)

        return JsonResponse({
            'success': True,
            'message': f'Analytics generated for {target_date or "yesterday"}'
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)