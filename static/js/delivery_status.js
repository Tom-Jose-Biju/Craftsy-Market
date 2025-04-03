// Function to update delivery status
function updateDeliveryStatus(url, status, notes = '', location = '') {
    // Get CSRF token from cookie
    const csrftoken = getCookie('csrftoken');

    // Prepare the request data
    const data = {
        status: status,
        notes: notes,
        location: location
    };

    // Make the API call with the provided URL
    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrftoken
        },
        body: JSON.stringify(data)
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            // Update UI to show success
            showNotification('success', data.message);
            // Update status in UI if needed
            updateStatusUI(status);
        } else {
            // Show error message
            showNotification('error', data.error || 'Failed to update status');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('error', 'Failed to update status. Please try again.');
    });
}

// Helper function to get CSRF token from cookies
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// Function to show notifications
function showNotification(type, message) {
    const notificationDiv = document.getElementById('notification');
    if (!notificationDiv) {
        // Create notification div if it doesn't exist
        const div = document.createElement('div');
        div.id = 'notification';
        div.style.position = 'fixed';
        div.style.top = '20px';
        div.style.right = '20px';
        div.style.padding = '15px';
        div.style.borderRadius = '5px';
        div.style.zIndex = '1000';
        document.body.appendChild(div);
    }
    
    const notification = document.getElementById('notification');
    notification.textContent = message;
    notification.className = `notification ${type}`;
    notification.style.backgroundColor = type === 'success' ? '#28a745' : '#dc3545';
    notification.style.color = 'white';
    notification.style.display = 'block';
    
    // Hide notification after 3 seconds
    setTimeout(() => {
        notification.style.display = 'none';
    }, 3000);
}

// Function to update status in UI
function updateStatusUI(status) {
    const statusElement = document.getElementById('delivery-status');
    if (statusElement) {
        statusElement.textContent = status.charAt(0).toUpperCase() + status.slice(1);
        statusElement.className = `status-badge ${status.toLowerCase()}`;
    }
} 