// Notification Manager Class
class NotificationManager {
    constructor() {
        this.unreadCount = 0;
        this.countBadge = document.getElementById('notification-count');
        this.setupEventListeners();
        this.updateUnreadCount();
    }

    setupEventListeners() {
        // Update unread count every minute
        setInterval(() => this.updateUnreadCount(), 60000);
    }

    async updateUnreadCount() {
        try {
            const response = await fetch('/notifications/unread-count/');
            const data = await response.json();
            this.unreadCount = data.count;
            this.updateCountDisplay();
        } catch (error) {
            console.error('Error updating notification count:', error);
        }
    }

    updateCountDisplay() {
        if (this.countBadge) {
            if (this.unreadCount > 0) {
                this.countBadge.textContent = this.unreadCount;
                this.countBadge.style.display = 'block';
            } else {
                this.countBadge.style.display = 'none';
            }
        }
    }

    async markAsRead(notificationId) {
        try {
            const response = await fetch(`/notifications/mark-read/${notificationId}/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                    'Content-Type': 'application/json'
                }
            });
            
            if (response.ok) {
                this.unreadCount = Math.max(0, this.unreadCount - 1);
                this.updateCountDisplay();
            }
        } catch (error) {
            console.error('Error marking notification as read:', error);
        }
    }

    async markAllAsRead() {
        try {
            const response = await fetch('/notifications/mark-all-read/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                    'Content-Type': 'application/json'
                }
            });
            
            if (response.ok) {
                this.unreadCount = 0;
                this.updateCountDisplay();
                
                // Update UI to show all notifications as read
                document.querySelectorAll('.notification-item').forEach(item => {
                    item.classList.remove('unread');
                });
            }
        } catch (error) {
            console.error('Error marking all notifications as read:', error);
        }
    }

    getCsrfToken() {
        const name = 'csrftoken';
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
}

// Initialize notification manager when document is ready
document.addEventListener('DOMContentLoaded', () => {
    window.notificationManager = new NotificationManager();
}); 