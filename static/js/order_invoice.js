function downloadPDF() {
    // Simple PDF generation using browser's print functionality
    // For more advanced PDF generation, you'd integrate with a library like jsPDF
    alert('PDF download functionality can be implemented with libraries like jsPDF or by generating PDFs server-side.');

    // Alternative: Open print dialog which allows "Save as PDF"
    window.print();
}

// Enhanced print function
function printInvoice() {
    // Hide non-essential elements before printing
    const elementsToHide = document.querySelectorAll('.d-print-none');
    elementsToHide.forEach(el => el.style.display = 'none');

    // Print
    window.print();

    // Restore elements after printing
    setTimeout(() => {
        elementsToHide.forEach(el => el.style.display = '');
    }, 1000);
}