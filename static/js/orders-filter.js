// orders-filter.js
// Simple, direct approach for orders search and filter functionality

let currentFilter = 'all';
let originalCount = 0;

function initializeOrdersFilter() {
    // Get original count from data attribute
    const container = document.querySelector('[data-original-count]');
    if (container) {
        originalCount = parseInt(container.getAttribute('data-original-count')) || 0;
    }

    console.log('Orders filter initialized with count:', originalCount);
    testSearch();
}

function performSearch() {
    const searchValue = document.getElementById('orderSearch').value.toLowerCase();
    const rows = document.querySelectorAll('.order-row');
    let visibleCount = 0;

    console.log('Searching for:', searchValue);
    console.log('Found rows:', rows.length);

    rows.forEach(function(row) {
        const orderId = (row.getAttribute('data-order-id') || '').toLowerCase();
        const customer = (row.getAttribute('data-customer') || '').toLowerCase();
        const amount = (row.getAttribute('data-amount') || '').toLowerCase();
        const status = (row.getAttribute('data-status') || '').toLowerCase();
        const date = (row.getAttribute('data-date') || '').toLowerCase();

        // Check if any field matches search
        const matchesSearch = !searchValue ||
            orderId.includes(searchValue) ||
            customer.includes(searchValue) ||
            amount.includes(searchValue) ||
            status.includes(searchValue) ||
            date.includes(searchValue);

        // Check if status matches filter
        const matchesFilter = currentFilter === 'all' || status === currentFilter;

        const shouldShow = matchesSearch && matchesFilter;

        if (shouldShow) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });

    console.log('Visible rows:', visibleCount);
    updateUI(visibleCount);
}

function applyFilter(filterValue, filterText) {
    currentFilter = filterValue;

    console.log('Applying filter:', filterValue);

    // Update button text
    const filterButton = document.getElementById('filterButton');
    if (filterButton) {
        filterButton.innerHTML = '<i class="fas fa-filter me-1"></i>' + filterText;
    }

    // Perform search with new filter
    performSearch();

    return false; // Prevent default link behavior
}

function clearAllFilters() {
    console.log('Clearing all filters');

    // Clear search input
    const searchInput = document.getElementById('orderSearch');
    if (searchInput) {
        searchInput.value = '';
    }

    // Reset filter
    currentFilter = 'all';

    // Reset button text
    const filterButton = document.getElementById('filterButton');
    if (filterButton) {
        filterButton.innerHTML = '<i class="fas fa-filter me-1"></i>All Orders';
    }

    // Show all rows
    const rows = document.querySelectorAll('.order-row');
    rows.forEach(function(row) {
        row.style.display = '';
    });

    updateUI(originalCount);
}

function updateUI(visibleCount) {
    // Update count
    const orderCountElement = document.getElementById('orderCount');
    if (orderCountElement) {
        orderCountElement.textContent = visibleCount;
    }

    // Show/hide no results message
    const noResults = document.getElementById('noResults');
    const ordersCard = document.getElementById('ordersCard');
    const pagination = document.getElementById('paginationNav');

    if (visibleCount === 0) {
        if (noResults) noResults.style.display = 'block';
        if (ordersCard) ordersCard.style.display = 'none';
    } else {
        if (noResults) noResults.style.display = 'none';
        if (ordersCard) ordersCard.style.display = 'block';
    }

    // Hide pagination when filtering
    const searchInput = document.getElementById('orderSearch');
    const isFiltered = currentFilter !== 'all' || (searchInput && searchInput.value !== '');
    if (pagination) {
        pagination.style.display = isFiltered ? 'none' : 'block';
    }
}

// Test function - you can call this in console to debug
function testSearch() {
    const rows = document.querySelectorAll('.order-row');
    console.log('Total rows found:', rows.length);

    if (rows.length > 0) {
        const firstRow = rows[0];
        console.log('First row data:');
        console.log('- Order ID:', firstRow.getAttribute('data-order-id'));
        console.log('- Customer:', firstRow.getAttribute('data-customer'));
        console.log('- Amount:', firstRow.getAttribute('data-amount'));
        console.log('- Status:', firstRow.getAttribute('data-status'));
        console.log('- Date:', firstRow.getAttribute('data-date'));
    }
}

// Auto-initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', initializeOrdersFilter);

// Also initialize on window load as backup
window.addEventListener('load', function() {
    console.log('Page loaded, testing search functionality...');
    if (originalCount === 0) {
        initializeOrdersFilter();
    }
});