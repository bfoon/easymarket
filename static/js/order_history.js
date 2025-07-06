function reorderItems(orderId) {
    fetch(`/orders/reorder/${orderId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value ||
                          document.querySelector('input[name="csrfmiddlewaretoken"]').value
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