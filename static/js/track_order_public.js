function refreshTracking() {
    const trackingNumber = document.getElementById('tracking_number').value;

    if (!trackingNumber) {
        alert('Please enter a tracking number first.');
        return;
    }

    // Show loading state
    const refreshBtn = event.target;
    const originalText = refreshBtn.innerHTML;
    refreshBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Refreshing...';
    refreshBtn.disabled = true;

    // Make AJAX request
    fetch(`/orders/track-ajax/?tracking_number=${encodeURIComponent(trackingNumber)}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Reload page to show updated information
                location.reload();
            } else {
                alert('Error refreshing tracking: ' + data.error);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Unable to refresh tracking information. Please try again.');
        })
        .finally(() => {
            // Restore button state
            refreshBtn.innerHTML = originalText;
            refreshBtn.disabled = false;
        });
}

// Auto-format tracking number input
document.getElementById('tracking_number').addEventListener('input', function(e) {
    let value = e.target.value.toUpperCase();
    // Remove any non-alphanumeric characters
    value = value.replace(/[^A-Z0-9]/g, '');
    e.target.value = value;
});

// Form submission enhancement
document.getElementById('trackingForm').addEventListener('submit', function(e) {
    const trackBtn = document.getElementById('trackBtn');
    const originalText = trackBtn.innerHTML;

    trackBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Tracking...';
    trackBtn.disabled = true;

    // The form will submit normally, but we show loading state
});