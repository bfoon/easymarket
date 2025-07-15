// Chat functionality
document.addEventListener('DOMContentLoaded', function () {
  const chatToggleBtn = document.getElementById('chatToggleBtn');
  const chatContainer = document.getElementById('chatContainer');
  const closeChatBtn = document.getElementById('closeChatBtn');
  const chatInput = document.getElementById('chatInput');
  const sendChatBtn = document.getElementById('sendChatBtn');
  const chatMessages = document.getElementById('chatMessages');
  const chatNotification = document.getElementById('chatNotification');

  let isChatOpen = false;

  function toggleChat() {
    isChatOpen = !isChatOpen;
    chatContainer.style.display = isChatOpen ? 'flex' : 'none';
    if (isChatOpen) {
      if (chatNotification) chatNotification.style.display = 'none';
      chatInput.focus();
    }
  }

  if (chatToggleBtn && closeChatBtn) {
    chatToggleBtn.addEventListener('click', toggleChat);
    closeChatBtn.addEventListener('click', toggleChat);
  }

  function sendMessage() {
    const message = chatInput.value.trim();
    if (message) {
      addMessage(message, 'user');
      chatInput.value = '';

      setTimeout(() => {
        const responses = [
          "I understand you're working on your product listing. Let me help you with that!",
          "Great question! For better product optimization, consider improving your product images and descriptions.",
          "I can help you with pricing strategies. What specific aspect would you like to discuss?",
          "For SEO optimization, focus on relevant keywords in your product title and description.",
          "I'm here to assist! Could you provide more details about what you need help with?",
        ];
        const randomResponse = responses[Math.floor(Math.random() * responses.length)];
        addMessage(randomResponse, 'bot');
      }, 1000);
    }
  }

  function addMessage(content, sender) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}-message`;

    const now = new Date();
    const timeString = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    messageDiv.innerHTML = `
      <div class="message-content">
        <p>${content}</p>
        <small class="message-time">${timeString}</small>
      </div>
    `;

    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  if (sendChatBtn && chatInput) {
    sendChatBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', function (e) {
      if (e.key === 'Enter') {
        sendMessage();
      }
    });
  }

  document.querySelectorAll('.quick-action').forEach(button => {
    button.addEventListener('click', function () {
      const message = this.getAttribute('data-message');
      chatInput.value = message;
      sendMessage();
    });
  });

  // Stock update
  window.updateStock = function (stockId) {
    const quantity = document.getElementById('stockQuantityInput').value;

    fetch(`/stock/update/${stockId}/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ quantity: quantity })
    })
    .then(res => res.json())
    .then(data => {
      alert(data.success ? "Stock updated successfully!" : "Failed to update stock.");
    })
    .catch(err => {
      console.error(err);
      alert("An error occurred.");
    });
  }

  // Image delete
  window.deleteImage = function (imageId) {
    if (confirm('Are you sure you want to delete this image?')) {
      fetch(`/stores/${storeId}/${productId}/delete-image/${imageId}/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
          'Content-Type': 'application/json'
        }
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          document.getElementById(`image-${imageId}`).remove();
        } else {
          alert(data.message);
        }
      })
      .catch(error => {
        console.error(error);
        alert('Error deleting image.');
      });
    }
  }

  // Auto-resize textareas
  document.querySelectorAll('textarea').forEach(el => {
    el.addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = this.scrollHeight + 'px';
    });
  });
});
