function suggestColor(imageId) {
    fetch(`/admin/marketplace/productimage/suggest-color/${imageId}/`)
        .then(response => response.json())
        .then(data => {
            if (data.success && data.suggested_color) {
                // Find the color input field for this image
                const colorInput = document.querySelector(`#id_images-${imageId}-color, input[name*="color"][id*="${imageId}"]`);
                if (colorInput) {
                    colorInput.value = data.suggested_color;
                    alert(`Suggested color: ${data.suggested_color}`);
                } else {
                    alert(`Suggested color: ${data.suggested_color}\nPlease enter this manually in the color field.`);
                }
            } else {
                alert('Could not suggest a color for this image.');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error suggesting color. Please try again.');
        });
}