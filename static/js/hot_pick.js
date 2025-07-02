// Flash Sale Countdown Timer
function updateCountdown() {
    const countdownElement = document.getElementById('countdown');
    if (!countdownElement) return;

    const now = new Date().getTime();
    const endTime = new Date(now + 24 * 60 * 60 * 1000).getTime();
    const distance = endTime - now;

    const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
    const seconds = Math.floor((distance % (1000 * 60)) / 1000);

    countdownElement.textContent =
        `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
}

// Update countdown every second
setInterval(updateCountdown, 1000);
updateCountdown();

// Animate statistics counters
function animateStats() {
    const stats = [
        { id: 'statProducts', target: '2.4M', numeric: 2.4 },
        { id: 'statCustomers', target: '847K', numeric: 847 },
        { id: 'statRating', target: '4.9', numeric: 4.9 },
        { id: 'statDelivery', target: '24H', numeric: 24 }
    ];

    stats.forEach(stat => {
        const element = document.getElementById(stat.id);
        if (!element) return;

        let current = 0;
        const increment = stat.numeric / 50;

        const timer = setInterval(() => {
            current += increment;
            if (current >= stat.numeric) {
                element.textContent = stat.target;
                clearInterval(timer);
            } else {
                if (stat.target.includes('M')) {
                    element.textContent = (current).toFixed(1) + 'M';
                } else if (stat.target.includes('K')) {
                    element.textContent = Math.floor(current) + 'K';
                } else if (stat.target.includes('H')) {
                    element.textContent = Math.floor(current) + 'H';
                } else {
                    element.textContent = current.toFixed(1);
                }
            }
        }, 50);
    });
}

// Scroll functionality for product carousel
document.addEventListener('DOMContentLoaded', function() {
    // Animate stats on page load
    setTimeout(animateStats, 500);

    const scrollLeft = document.querySelector('.scroll-left');
    const scrollRight = document.querySelector('.scroll-right');
    const container = document.querySelector('.products-container');

    if (scrollLeft && scrollRight && container) {
        scrollLeft.addEventListener('click', () => {
            container.scrollBy({ left: -200, behavior: 'smooth' });
        });

        scrollRight.addEventListener('click', () => {
            container.scrollBy({ left: 200, behavior: 'smooth' });
        });
    }
});

// Add to Cart functionality
function addToCart(productId) {
    // Find the button that was clicked
    const button = event.target.closest('.btn-cart');
    if (!button) return;

    const originalText = button.innerHTML;
    button.innerHTML = '<i class="fas fa-check"></i> ADDED';
    button.style.backgroundColor = 'var(--success-green)';

    // Here you would typically make an AJAX call to add the product to cart
    // Example:
    /*
    fetch(`/cart/add/${productId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            'product_id': productId,
            'quantity': 1
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update cart count in header if needed
            updateCartCount(data.cart_count);
        }
    });
    */

    setTimeout(() => {
        button.innerHTML = originalText;
        button.style.backgroundColor = 'var(--amazon-orange)';
    }, 2000);
}