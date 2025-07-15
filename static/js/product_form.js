// product_form.js

document.addEventListener('DOMContentLoaded', function () {
  const storeId = window.storeId || null;
  const productId = window.productId || null;
  const form = document.getElementById('productForm');

  if (!form) return;

  const nameField = form.querySelector('[name="name"]');
  const descField = form.querySelector('[name="description"]');
  const priceField = form.querySelector('[name="price"]');
  const originalPriceField = form.querySelector('[name="original_price"]');
  const imageField = form.querySelector('[name="image"]');

  // Character counters
  if (nameField) {
    updateCounter(nameField, 'nameCounter', 100);
    nameField.addEventListener('input', () => updateCounter(nameField, 'nameCounter', 100));
  }

  if (descField) {
    updateCounter(descField, 'descCounter', 1000);
    descField.addEventListener('input', () => updateCounter(descField, 'descCounter', 1000));
  }

  // Price calculation
  if (priceField && originalPriceField) {
    [priceField, originalPriceField].forEach(field => {
      field.addEventListener('input', calculateDiscount);
    });
    calculateDiscount();
  }

  // Image preview
  if (imageField) {
    imageField.addEventListener('change', handleImagePreview);
  }

  // Form submit validation
  form.addEventListener('submit', handleFormSubmit);

  // Auto-save setup
  let autoSaveTimeout;
  form.addEventListener('input', function () {
    clearTimeout(autoSaveTimeout);
    autoSaveTimeout = setTimeout(autoSave, 30000); // Save after 30s inactivity
  });
});

function updateCounter(field, counterId, maxLength) {
  const counter = document.getElementById(counterId);
  if (counter) {
    const length = field.value.length;
    counter.textContent = length;
    counter.parentElement.className = length > maxLength * 0.9 ? 'form-text text-warning' : 'form-text';
  }
}

function calculateDiscount() {
  const price = parseFloat(document.querySelector('[name="price"]').value) || 0;
  const originalPrice = parseFloat(document.querySelector('[name="original_price"]').value) || 0;
  const discountInfo = document.getElementById('discountInfo');

  if (discountInfo && price && originalPrice > price) {
    const discount = ((originalPrice - price) / originalPrice * 100).toFixed(1);
    discountInfo.innerHTML = `<span class="text-success"><i class="fas fa-percentage me-1"></i>${discount}% discount</span>`;
  } else if (discountInfo) {
    discountInfo.innerHTML = '';
  }
}

function handleImagePreview(event) {
  const file = event.target.files[0];
  const preview = document.getElementById('imagePreview');
  const previewImg = document.getElementById('previewImg');

  if (file && file.type.startsWith('image/')) {
    const reader = new FileReader();
    reader.onload = function (e) {
      previewImg.src = e.target.result;
      preview.classList.remove('d-none');
    };
    reader.readAsDataURL(file);
  } else {
    preview.classList.add('d-none');
  }
}

function handleFormSubmit(event) {
  const form = event.target;
  const submitBtn = document.getElementById('saveChangesBtn');
  const overlay = document.getElementById('loadingOverlay');

  // Show loading
  submitBtn.disabled = true;
  submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Saving...';
  overlay.classList.remove('d-none');

  let isValid = true;
  const requiredFields = form.querySelectorAll('[required]');

  requiredFields.forEach(field => {
    if (!field.value.trim()) {
      field.classList.add('is-invalid');
      isValid = false;
    } else {
      field.classList.remove('is-invalid');
    }
  });

  if (!isValid) {
    event.preventDefault();
    submitBtn.disabled = false;
    submitBtn.innerHTML = '<i class="fas fa-check me-1"></i>Save Changes';
    overlay.classList.add('d-none');

    const firstInvalid = form.querySelector('.is-invalid');
    if (firstInvalid) {
      firstInvalid.focus();
      firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }
}

function deleteImage(imageId) {
  if (confirm('Are you sure you want to delete this image?')) {
    const imageContainer = document.getElementById(`image-${imageId}`);
    if (imageContainer) {
      imageContainer.remove();

      const deleteInput = document.createElement('input');
      deleteInput.type = 'hidden';
      deleteInput.name = `delete_image_${imageId}`;
      deleteInput.value = 'true';
      document.getElementById('productForm').appendChild(deleteInput);
    }
  }
}

function autoSave() {
  console.log('Auto-saving form...');
}
