// Add debugging and ensure DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded');
    console.log('Bootstrap available:', typeof bootstrap !== 'undefined');
    console.log('jQuery available:', typeof $ !== 'undefined');
    console.log('Payment modal exists:', document.getElementById('paymentModal') !== null);

    // Test modal functionality
    const testModal = document.getElementById('paymentModal');
    if (testModal) {
        console.log('Payment modal found in DOM');

        // Add click event to close buttons for manual fallback
        const closeButtons = testModal.querySelectorAll('[data-bs-dismiss="modal"]');
        closeButtons.forEach(button => {
            button.addEventListener('click', closePaymentModal);
        });

        // Add click event to backdrop for manual fallback
        testModal.addEventListener('click', function(e) {
            if (e.target === testModal) {
                closePaymentModal();
            }
        });
    } else {
        console.error('Payment modal not found in DOM');
    }
});

function proceedToPayment(orderId) {
    console.log('proceedToPayment called with orderId:', orderId);

    try {
        // Method 1: Bootstrap 5 native JavaScript API
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            console.log('Using Bootstrap 5 Modal API');
            const paymentModal = new bootstrap.Modal(document.getElementById('paymentModal'));
            paymentModal.show();
            return;
        }

        // Method 2: jQuery fallback (if available)
        if (typeof $ !== 'undefined' && $.fn.modal) {
            console.log('Using jQuery Modal API');
            $('#paymentModal').modal('show');
            return;
        }

        // Method 3: Manual display fallback
        console.log('Using manual modal display');
        const modal = document.getElementById('paymentModal');
        if (modal) {
            modal.classList.add('show');
            modal.style.display = 'block';
            modal.setAttribute('aria-hidden', 'false');

            // Add backdrop
            const backdrop = document.createElement('div');
            backdrop.className = 'modal-backdrop fade show';
            backdrop.id = 'paymentModalBackdrop';
            document.body.appendChild(backdrop);

            // Add body class
            document.body.classList.add('modal-open');

            console.log('Modal displayed manually');
        } else {
            console.error('Payment modal element not found');
        }

    } catch (error) {
        console.error('Error opening payment modal:', error);
        alert('Unable to open payment form. Please refresh the page and try again.');
    }
}

// Function to manually close modal (for fallback method)
function closePaymentModal() {
    const modal = document.getElementById('paymentModal');
    const backdrop = document.getElementById('paymentModalBackdrop');

    if (modal) {
        modal.classList.remove('show');
        modal.style.display = 'none';
        modal.setAttribute('aria-hidden', 'true');
    }

    if (backdrop) {
        backdrop.remove();
    }

    document.body.classList.remove('modal-open');
}

function processPayment() {
    const formData = new FormData(document.getElementById('paymentForm'));

    fetch(`/orders/process-payment/{{ order.id }}/`, {
        method: 'POST',
        body: formData,
        headers: {
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Payment successful! Your order is being processed.');
            location.reload();
        } else {
            alert('Payment failed: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred during payment processing.');
    });
}

function trackOrder(orderId) {
    window.location.href = `/orders/track/${orderId}/`;
}

function reorderItems(orderId) {
    fetch(`/orders/reorder/${orderId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Items added to cart successfully!');
            window.location.href = '/cart/';
        } else {
            alert('Error: ' + data.error);
        }
    });
}

function cancelOrder(orderId) {
    // Store the order ID for later use
    window.currentOrderToCancel = orderId;

    // Show the confirmation modal
    const cancelModal = new bootstrap.Modal(document.getElementById('cancelOrderModal'));
    cancelModal.show();
}

function confirmCancelOrder() {
    const orderId = window.currentOrderToCancel;
    if (!orderId) return;

    // Show loading state
    const confirmBtn = document.getElementById('confirmCancelBtn');
    const originalText = confirmBtn.innerHTML;
    confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Cancelling...';
    confirmBtn.disabled = true;

    fetch(`/orders/cancel/${orderId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
            'Content-Type': 'application/json',
        }
    })
    .then(response => {
        if (response.ok) {
            // Hide modal and reload page to show updated status
            bootstrap.Modal.getInstance(document.getElementById('cancelOrderModal')).hide();

            // Show success message
            showSuccessMessage('Order cancelled successfully. Stock has been restored.');

            // Reload page after a short delay
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        } else {
            throw new Error('Failed to cancel order');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred while cancelling the order. Please try again.');

        // Restore button state
        confirmBtn.innerHTML = originalText;
        confirmBtn.disabled = false;
    });
}

function showSuccessMessage(message) {
    // Create and show a success alert
    const alertHtml = `
        <div class="alert alert-success alert-dismissible fade show position-fixed"
             style="top: 20px; right: 20px; z-index: 9999; min-width: 300px;" role="alert">
            <i class="fas fa-check-circle me-2"></i>
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', alertHtml);
}

// Add CSS for status badges
const style = document.createElement('style');
style.textContent = `
    .badge-pending { background-color: #ffc107; color: #000; }
    .badge-processing { background-color: #17a2b8; color: #fff; }
    .badge-shipped { background-color: #28a745; color: #fff; }
    .badge-delivered { background-color: #6f42c1; color: #fff; }
    .badge-cancelled { background-color: #dc3545; color: #fff; }
`;
document.head.appendChild(style);