document.addEventListener('DOMContentLoaded', function () {
    console.log('DOM loaded');
    initializePaymentFeatures();
});

// Initialize payment-specific features
function initializePaymentFeatures() {
    const paymentMethodSelect = document.getElementById('paymentMethod');
    if (paymentMethodSelect) {
        paymentMethodSelect.addEventListener('change', function () {
            showPaymentFields(this.value);
        });
    }
    setupCardInputFormatting();
    setupMobileInputFormatting();
}

function showPaymentFields(method) {
    const mobileFields = document.getElementById('mobilePaymentFields');
    const cardFields = document.getElementById('verveCardFields');
    const cashNote = document.getElementById('cashNote');

    if (mobileFields) mobileFields.classList.add('d-none');
    if (cardFields) cardFields.classList.add('d-none');
    if (cashNote) cashNote.classList.add('d-none');

    if (['wave', 'qmoney', 'afrimoney'].includes(method) && mobileFields) {
        mobileFields.classList.remove('d-none');
    } else if (method === 'verve_card' && cardFields) {
        cardFields.classList.remove('d-none');
    } else if (method === 'cash' && cashNote) {
        cashNote.classList.remove('d-none');
    }
}

function setupCardInputFormatting() {
    const cardNumber = document.querySelector('input[name="card_number"]');
    const expiry = document.querySelector('input[name="card_expiry"]');
    const cvv = document.querySelector('input[name="card_cvv"]');

    if (cardNumber) {
        cardNumber.addEventListener('input', (e) => {
            let val = e.target.value.replace(/\s/g, '').slice(0, 19);
            e.target.value = val.replace(/(.{4})/g, '$1 ').trim();
        });
    }

    if (expiry) {
        expiry.addEventListener('input', (e) => {
            let val = e.target.value.replace(/\D/g, '').slice(0, 4);
            if (val.length > 2) val = `${val.slice(0, 2)}/${val.slice(2)}`;
            e.target.value = val;
        });
    }

    if (cvv) {
        cvv.addEventListener('input', (e) => {
            e.target.value = e.target.value.replace(/\D/g, '').slice(0, 4);
        });
    }
}

function setupMobileInputFormatting() {
    const mobileInput = document.querySelector('input[name="mobile_number"]');
    if (mobileInput) {
        mobileInput.addEventListener('input', (e) => {
            e.target.value = e.target.value.replace(/[^\d\s+()-]/g, '');
        });
    }
}

function proceedToPayment(orderId) {
    window.currentOrderId = orderId;
    const form = document.getElementById('paymentForm');
    if (form) form.reset();
    showPaymentFields('');

    const modalEl = document.getElementById('paymentModal');
    if (modalEl) {
        const modal = new bootstrap.Modal(modalEl);
        modal.show();
    }
}

async function processPayment(orderId) {
    const form = document.getElementById('paymentForm');
    const formData = new FormData(form);

    if (!validatePaymentForm(formData)) return;

    const submitBtn = event.target;
    const originalText = submitBtn.innerHTML;
    submitBtn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i>Processing...`;
    submitBtn.disabled = true;

    const paymentMethod = formData.get('payment_method');
    const paymentData = { payment_method: paymentMethod };

    if (['wave', 'qmoney', 'afrimoney'].includes(paymentMethod)) {
        paymentData.phone_number = formData.get('mobile_number');
        paymentData.pin = formData.get('pin');
    } else if (paymentMethod === 'verve_card') {
        paymentData.card_number = formData.get('card_number');
        paymentData.expiry_date = formData.get('card_expiry');
        paymentData.cvv = formData.get('card_cvv');
        paymentData.cardholder_name = formData.get('cardholder_name') || 'Card Holder';
    }

    try {
        const res = await fetch(`/payments/process/${orderId}/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
            body: JSON.stringify(paymentData)
        });
        const result = await res.json();

        if (result.success) {
            showPaymentSuccess(result);
            const modalEl = document.getElementById('paymentModal');
            if (modalEl) bootstrap.Modal.getInstance(modalEl)?.hide();
            setTimeout(() => window.location.reload(), 2000);
        } else {
            showPaymentError(result.error);
        }
    } catch (err) {
        console.error(err);
        showPaymentError('An unexpected error occurred.');
    } finally {
        submitBtn.innerHTML = originalText;
        submitBtn.disabled = false;
    }
}

function validatePaymentForm(formData) {
    const method = formData.get('payment_method');
    if (!method) return showAlert('Select a payment method', 'danger'), false;
    const agreeTerms = document.getElementById('agreeTerms');
    if (agreeTerms && !agreeTerms.checked) return showAlert('Agree to terms', 'danger'), false;

    if (['wave', 'qmoney', 'afrimoney'].includes(method)) {
        const phone = formData.get('mobile_number'), pin = formData.get('pin');
        if (!phone || !pin || !/^\+?[\d\s-()]+$/.test(phone))
            return showAlert('Enter valid mobile details', 'danger'), false;
    } else if (method === 'verve_card') {
        const card = formData.get('card_number'), exp = formData.get('card_expiry'),
              cvv = formData.get('card_cvv'), name = formData.get('cardholder_name');
        if (!card || !exp || !cvv || !name || !/^\d{13,19}$/.test(card.replace(/\s/g, '')) ||
            !/^\d{2}\/\d{2}$/.test(exp) || !/^\d{3,4}$/.test(cvv))
            return showAlert('Enter valid card details', 'danger'), false;
    }
    return true;
}

function cancelOrder(orderId) {
    window.currentOrderToCancel = orderId;
    const modalEl = document.getElementById('cancelOrderModal');
    if (modalEl) {
        window.cancelModalInstance = new bootstrap.Modal(modalEl);
        window.cancelModalInstance.show();
    } else if (confirm('Cancel this order?')) {
        confirmCancelOrder();
    }
}

function confirmCancelOrder() {
    const orderId = window.currentOrderToCancel;
    if (!orderId) return showAlert('No order selected', 'danger');

    const btn = document.getElementById('confirmCancelBtn');
    const originalText = btn ? btn.innerHTML : '';

    if (btn) {
        btn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i>Cancelling...`;
        btn.disabled = true;
    }

    fetch(`/orders/cancel/${orderId}/`, {
        method: 'POST',
        headers: {
        'X-CSRFToken': getCSRFToken(),
        'Content-Type': 'application/json',
         'X-Requested-With': 'XMLHttpRequest'
         }
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            window.cancelModalInstance?.hide();
            showSuccessMessage('Order cancelled.');
            setTimeout(() => window.location.reload(), 2000);
        } else throw new Error(data.error);
    })
    .catch(err => {
        console.error(err);
        showAlert(err.message || 'Error cancelling order', 'danger');
        if (btn) {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });
}

function trackOrder(orderId) {
    const url = `/orders/track/${orderId}/`;
    fetch(url, { headers: { 'X-CSRFToken': getCSRFToken() } })
        .then(res => res.ok ? window.location.href = url : showAlert('Tracking unavailable', 'info'))
        .catch(() => window.location.href = url);
}

function reorderItems(orderId) {
    if (!confirm('Add all items from this order to your cart?')) return;
    fetch(`/orders/reorder/${orderId}/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCSRFToken(), 'Content-Type': 'application/json' }
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            showSuccessMessage('Items added to cart!');
            setTimeout(() => window.location.href = '/cart/', 1500);
        } else {
            showAlert(data.error || 'Unable to reorder', 'danger');
        }
    })
    .catch(() => showAlert('Error adding items to cart', 'danger'));
}

function showPaymentSuccess(result) {
    showAlert(`<strong>Payment Successful!</strong> ${result.message} ${result.transaction_id ? `<br><small>Transaction ID: ${result.transaction_id}</small>` : ''}`, 'success');
}

function showPaymentError(message) {
    showAlert(message, 'danger');
}

function showSuccessMessage(message) {
    const html = `<div class="alert alert-success alert-dismissible fade show position-fixed" style="top:20px;right:20px;z-index:9999;min-width:300px;">
        <i class="fas fa-check-circle me-2"></i>${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    setTimeout(() => document.querySelector('.alert-success.position-fixed')?.remove(), 5000);
}

function showAlert(message, type = 'info') {
    document.querySelectorAll('.alert').forEach(e => e.remove());
    const icon = type === 'danger' ? 'exclamation-triangle' : 'info-circle';
    const html = `<div class="alert alert-${type} alert-dismissible fade show" role="alert">
        <i class="fas fa-${icon} me-2"></i>${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>`;
    document.querySelector('.container')?.insertAdjacentHTML('afterbegin', html);
    window.scrollTo(0, 0);
    setTimeout(() => document.querySelector('.alert')?.remove(), 5000);
}

function getCSRFToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
}
