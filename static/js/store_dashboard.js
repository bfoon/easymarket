document.addEventListener('DOMContentLoaded', function() {
    // Update last updated timestamp
    document.getElementById('lastUpdated').textContent = new Date().toLocaleDateString();

    // Chart variables
    let salesChart;
    let categoryChart;

    // Initialize Sales Chart
    const salesCtx = document.getElementById('salesChart');
    if (salesCtx) {
        salesChart = new Chart(salesCtx, {
            type: 'line',
            data: {
                labels: window.chartData.monthlyLabels,
                datasets: [{
                    label: 'Sales (D)',
                    data: window.chartData.monthlySalesData,
                    borderColor: '#007bff',
                    backgroundColor: 'rgba(0, 123, 255, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return 'D' + value;
                            }
                        }
                    }
                },
                interaction: {
                    intersect: false,
                    mode: 'index'
                },
                layout: {
                    padding: {
                        top: 10,
                        bottom: 10
                    }
                }
            }
        });
    }

    // Initialize Category Chart
    const categoryCtx = document.getElementById('categoryChart');
    if (categoryCtx) {
        categoryChart = new Chart(categoryCtx, {
            type: 'doughnut',
            data: {
                labels: window.chartData.categoryLabels,
                datasets: [{
                    data: window.chartData.categoryData,
                    backgroundColor: [
                        '#007bff',
                        '#28a745',
                        '#ffc107',
                        '#dc3545',
                        '#6c757d',
                        '#17a2b8'
                    ],
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 8,
                            usePointStyle: true,
                            font: {
                                size: 11
                            }
                        }
                    }
                },
                layout: {
                    padding: {
                        top: 5,
                        bottom: 5
                    }
                }
            }
        });
    }

    // Chart type switching functionality (if you want to keep the enhanced features)
    const chartTypeRadios = document.querySelectorAll('input[name="chartType"]');
    if (chartTypeRadios.length > 0) {
        chartTypeRadios.forEach(function(radio) {
            radio.addEventListener('change', function() {
                updateSalesChart(this.value);
            });
        });
    }

    // Function to update sales chart based on selected type
    function updateSalesChart(chartType) {
        if (!salesChart) return;

        let data, label, color;

        switch(chartType) {
            case 'sales':
                data = window.chartData.monthlySalesData;
                label = 'Sales (D)';
                color = '#007bff';
                break;
            case 'orders':
                data = window.chartData.monthlyOrdersData || window.chartData.monthlySalesData;
                label = 'Orders';
                color = '#28a745';
                break;
            case 'visitors':
                data = window.chartData.monthlyVisitorsData || window.chartData.monthlySalesData;
                label = 'Visitors';
                color = '#ffc107';
                break;
            default:
                data = window.chartData.monthlySalesData;
                label = 'Sales (D)';
                color = '#007bff';
        }

        // Update chart data
        salesChart.data.datasets[0].data = data;
        salesChart.data.datasets[0].label = label;
        salesChart.data.datasets[0].borderColor = color;
        salesChart.data.datasets[0].backgroundColor = color + '20'; // Add transparency

        // Update y-axis formatting
        salesChart.options.scales.y.ticks.callback = function(value) {
            if (chartType === 'sales') {
                return 'D' + value;
            }
            return value;
        };

        salesChart.update('none'); // Update without animation for stability
    }

    // Initialize tooltips (if Bootstrap is available)
    if (typeof bootstrap !== 'undefined') {
        var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    // Initialize counter animations
    animateCounters();

    // Refresh dashboard button
    const refreshBtn = document.getElementById('refreshDashboard');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', function() {
            this.innerHTML = '<i class="fas fa-spin fa-sync-alt"></i>';

            setTimeout(function() {
                location.reload();
            }, 1000);
        });
    }

    // Time period filter functionality
    const timePeriodRadios = document.querySelectorAll('input[name="timePeriod"]');
    if (timePeriodRadios.length > 0) {
        timePeriodRadios.forEach(function(radio) {
            radio.addEventListener('change', function() {
                updateDashboardData(this.value);
            });
        });
    }

    // Order filtering
    const orderFilterRadios = document.querySelectorAll('input[name="orderFilter"]');
    if (orderFilterRadios.length > 0) {
        orderFilterRadios.forEach(function(radio) {
            radio.addEventListener('change', filterOrders);
        });
    }

    // Product sorting
    const productSortSelect = document.getElementById('productSortBy');
    if (productSortSelect) {
        productSortSelect.addEventListener('change', sortProducts);
    }

    // Process order buttons
    const processOrderBtns = document.querySelectorAll('.process-order');
    if (processOrderBtns.length > 0) {
        processOrderBtns.forEach(function(btn) {
            btn.addEventListener('click', function() {
                processOrder(this.dataset.orderId);
            });
        });
    }

    // Export functionality
    const exportPDFBtn = document.getElementById('exportPDF');
    const exportExcelBtn = document.getElementById('exportExcel');

    if (exportPDFBtn) {
        exportPDFBtn.addEventListener('click', function(e) {
            e.preventDefault();
            showToast('PDF export feature coming soon!', 'info');
        });
    }

    if (exportExcelBtn) {
        exportExcelBtn.addEventListener('click', function(e) {
            e.preventDefault();
            showToast('Excel export feature coming soon!', 'info');
        });
    }

    // Auto-refresh dashboard every 5 minutes (same as original)
    setInterval(function() {
        if (document.hidden) return; // Don't refresh if tab is not active

        // Update timestamp
        document.getElementById('lastUpdated').textContent = new Date().toLocaleDateString();
    }, 60000); // Update timestamp every minute

    // Full page refresh every 5 minutes
    setInterval(function() {
        if (!document.hidden) {
            location.reload();
        }
    }, 300000);
});

// Animate counter numbers
function animateCounters() {
    const counters = document.querySelectorAll('.counter');
    if (counters.length === 0) return;

    counters.forEach(function(counter) {
        const target = parseInt(counter.dataset.target) || 0;
        if (target === 0) {
            counter.textContent = '0';
            return;
        }

        let current = 0;
        const increment = target / 100;
        const timer = setInterval(function() {
            current += increment;
            counter.textContent = Math.floor(current).toLocaleString();
            if (current >= target) {
                counter.textContent = target.toLocaleString();
                clearInterval(timer);
            }
        }, 20);
    });
}

// Update dashboard data based on time period
function updateDashboardData(period) {
    // Show loading modal if Bootstrap is available
    if (typeof bootstrap !== 'undefined') {
        const loadingModalEl = document.getElementById('loadingModal');
        if (loadingModalEl) {
            const loadingModal = new bootstrap.Modal(loadingModalEl);
            loadingModal.show();

            setTimeout(function() {
                loadingModal.hide();
                showToast('Dashboard updated for ' + period + ' days period', 'success');
            }, 2000);
        }
    } else {
        // Fallback without modal
        setTimeout(function() {
            showToast('Dashboard updated for ' + period + ' days period', 'success');
        }, 1000);
    }

    console.log('Updating dashboard for period:', period + ' days');
}

// Copy to clipboard functionality
function copyToClipboard(text) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(function() {
            showToast('URL copied to clipboard!', 'success');
        }).catch(function() {
            fallbackCopyTextToClipboard(text);
        });
    } else {
        fallbackCopyTextToClipboard(text);
    }
}

// Fallback for older browsers
function fallbackCopyTextToClipboard(text) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    textArea.style.left = "-999999px";
    textArea.style.top = "-999999px";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();

    try {
        document.execCommand('copy');
        showToast('URL copied to clipboard!', 'success');
    } catch (err) {
        showToast('Could not copy URL', 'error');
    }

    document.body.removeChild(textArea);
}

// Filter orders by status
function filterOrders() {
    const filter = document.querySelector('input[name="orderFilter"]:checked');
    if (!filter) return;

    const filterValue = filter.value;
    const rows = document.querySelectorAll('#ordersTableBody tr[data-order-status]');

    rows.forEach(function(row) {
        if (filterValue === 'all' || row.dataset.orderStatus === filterValue) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

// Sort products
function sortProducts() {
    const sortBy = this.value;
    showToast('Sorting products by: ' + sortBy, 'info');

    // You would typically make an AJAX call here to resort the products
    console.log('Sort products by:', sortBy);
}

// Process order
function processOrder(orderId) {
    if (confirm('Mark this order as processed?')) {
        const button = document.querySelector(`[data-order-id="${orderId}"]`);
        if (!button) return;

        const originalContent = button.innerHTML;
        button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        button.disabled = true;

        // Simulate API call
        setTimeout(function() {
            button.innerHTML = '<i class="fas fa-check"></i>';
            button.classList.remove('btn-outline-success');
            button.classList.add('btn-success');
            button.disabled = false;
            showToast('Order #' + orderId + ' marked as processed!', 'success');

            // Update order status in the table
            const row = button.closest('tr');
            if (row) {
                const statusBadge = row.querySelector('.badge');
                if (statusBadge) {
                    statusBadge.textContent = 'Processing';
                    statusBadge.className = 'badge bg-info';
                }
            }
        }, 1500);
    }
}

// Show toast notifications
function showToast(message, type = 'info') {
    // Create toast container if it doesn't exist
    let toastContainer = document.getElementById('toastContainer');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toastContainer';
        toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
        toastContainer.style.zIndex = '1055';
        document.body.appendChild(toastContainer);
    }

    // Create toast element
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.id = toastId;
    toast.className = `toast align-items-center text-white bg-${type} border-0`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');

    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <i class="fas fa-${getToastIcon(type)} me-2"></i>${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;

    toastContainer.appendChild(toast);

    // Initialize and show toast
    if (typeof bootstrap !== 'undefined') {
        const bsToast = new bootstrap.Toast(toast, {
            autohide: true,
            delay: 5000
        });
        bsToast.show();

        // Remove toast from DOM after it's hidden
        toast.addEventListener('hidden.bs.toast', function() {
            if (toastContainer.contains(toast)) {
                toastContainer.removeChild(toast);
            }
        });
    } else {
        // Fallback without Bootstrap
        setTimeout(function() {
            if (toastContainer.contains(toast)) {
                toastContainer.removeChild(toast);
            }
        }, 5000);
    }
}

// Get appropriate icon for toast type
function getToastIcon(type) {
    switch(type) {
        case 'success': return 'check-circle';
        case 'error':
        case 'danger': return 'exclamation-circle';
        case 'warning': return 'exclamation-triangle';
        case 'info':
        default: return 'info-circle';
    }
}

// Get CSRF token for Django
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}