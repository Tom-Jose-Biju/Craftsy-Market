class DeliveryTracker {
    constructor(deliveryId) {
        this.deliveryId = deliveryId;
        this.socket = null;
        this.map = null;
        this.marker = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000; // Start with 1 second delay
        
        this.connect();
        this.initializeMap();
    }
    
    connect() {
        const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${wsScheme}://${window.location.host}/ws/delivery/${this.deliveryId}/`;
        
        this.socket = new WebSocket(wsUrl);
        
        this.socket.onopen = () => {
            console.log('WebSocket connection established');
            this.reconnectAttempts = 0;
            this.reconnectDelay = 1000;
            
            // Update connection status
            document.getElementById('connection-status').classList.remove('disconnected');
            document.getElementById('connection-status').classList.add('connected');
        };
        
        this.socket.onclose = (e) => {
            console.log('WebSocket connection closed');
            document.getElementById('connection-status').classList.remove('connected');
            document.getElementById('connection-status').classList.add('disconnected');
            
            // Attempt to reconnect
            this.tryReconnect();
        };
        
        this.socket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
        
        this.socket.onmessage = (e) => {
            const data = JSON.parse(e.data);
            this.handleMessage(data);
        };
    }
    
    tryReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            setTimeout(() => {
                console.log(`Attempting to reconnect (${this.reconnectAttempts + 1}/${this.maxReconnectAttempts})`);
                this.connect();
                this.reconnectAttempts++;
                this.reconnectDelay *= 2; // Exponential backoff
            }, this.reconnectDelay);
        } else {
            console.log('Max reconnection attempts reached');
            this.showError('Connection lost. Please refresh the page.');
        }
    }
    
    handleMessage(data) {
        switch (data.type) {
            case 'location_update':
                this.updateLocation(data.latitude, data.longitude);
                break;
                
            case 'status_update':
                this.updateStatus(data.status, data.notes, data.timestamp);
                break;
                
            case 'eta_update':
                this.updateETA(data.eta, data.current_location);
                break;
                
            case 'error':
                this.showError(data.message);
                break;
                
            default:
                console.warn('Unknown message type:', data.type);
        }
    }
    
    initializeMap() {
        this.map = L.map('delivery-map').setView([0, 0], 13);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors'
        }).addTo(this.map);
        
        this.marker = L.marker([0, 0]).addTo(this.map);
    }
    
    updateLocation(latitude, longitude) {
        const latLng = [latitude, longitude];
        this.marker.setLatLng(latLng);
        this.map.setView(latLng, 15);
        
        // Update location info in UI
        document.getElementById('current-location').textContent = 
            `Current Location: ${latitude.toFixed(6)}, ${longitude.toFixed(6)}`;
    }
    
    updateStatus(status, notes, timestamp) {
        // Update status in UI
        const statusElement = document.getElementById('delivery-status');
        statusElement.textContent = status.charAt(0).toUpperCase() + status.slice(1);
        statusElement.className = `status-badge ${status}`;
        
        // Add to status history
        const historyContainer = document.getElementById('status-history');
        const statusItem = document.createElement('div');
        statusItem.className = 'status-item';
        statusItem.innerHTML = `
            <span class="status-dot ${status}"></span>
            <div class="status-details">
                <div class="status-text">${status}</div>
                <div class="status-notes">${notes}</div>
                <div class="status-time">${new Date(timestamp).toLocaleString()}</div>
            </div>
        `;
        historyContainer.insertBefore(statusItem, historyContainer.firstChild);
    }
    
    updateETA(eta, currentLocation) {
        // Update ETA in UI
        document.getElementById('estimated-delivery').textContent = 
            `Estimated Delivery: ${new Date(eta).toLocaleString()}`;
            
        if (currentLocation) {
            this.updateLocation(currentLocation.lat, currentLocation.lng);
        }
    }
    
    showError(message) {
        const errorContainer = document.getElementById('error-container');
        errorContainer.textContent = message;
        errorContainer.style.display = 'block';
        
        setTimeout(() => {
            errorContainer.style.display = 'none';
        }, 5000);
    }
    
    disconnect() {
        if (this.socket) {
            this.socket.close();
        }
    }
}
