class DeliveryPartnerApp {
    constructor(deliveryId) {
        this.deliveryId = deliveryId;
        this.watchId = null;
        this.socket = null;
        this.initializeWebSocket();
    }

    initializeWebSocket() {
        this.socket = new WebSocket(
            'ws://' + window.location.host + '/ws/delivery/' + this.deliveryId + '/'
        );

        this.socket.onopen = () => {
            console.log('WebSocket connection established');
            this.startLocationTracking();
        };

        this.socket.onclose = () => {
            console.log('WebSocket connection closed');
            this.stopLocationTracking();
        };

        this.socket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    startLocationTracking() {
        if ('geolocation' in navigator) {
            const options = {
                enableHighAccuracy: true,
                timeout: 5000,
                maximumAge: 0
            };

            this.watchId = navigator.geolocation.watchPosition(
                position => this.handleLocationUpdate(position),
                error => this.handleLocationError(error),
                options
            );
        } else {
            console.error('Geolocation is not supported by this browser.');
        }
    }

    stopLocationTracking() {
        if (this.watchId !== null) {
            navigator.geolocation.clearWatch(this.watchId);
            this.watchId = null;
        }
    }

    async handleLocationUpdate(position) {
        const { latitude, longitude } = position.coords;

        // Send location update to server
        try {
            const response = await fetch(`/delivery/${this.deliveryId}/update-location/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({ latitude, longitude })
            });

            if (!response.ok) {
                throw new Error('Failed to update location');
            }

        } catch (error) {
            console.error('Error updating location:', error);
        }

        // Send location update via WebSocket
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify({
                type: 'location_update',
                latitude: latitude,
                longitude: longitude
            }));
        }
    }

    handleLocationError(error) {
        console.error('Error getting location:', error);
    }

    getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]').value;
    }

    async updateDeliveryStatus(status, notes = '', location = '') {
        try {
            const response = await fetch(`/delivery/${this.deliveryId}/update-status/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({ status, notes, location })
            });

            if (!response.ok) {
                throw new Error('Failed to update status');
            }

            // Send status update via WebSocket
            if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                this.socket.send(JSON.stringify({
                    type: 'status_update',
                    status: status,
                    notes: notes,
                    location: location
                }));
            }

            return await response.json();

        } catch (error) {
            console.error('Error updating status:', error);
            throw error;
        }
    }

    disconnect() {
        this.stopLocationTracking();
        if (this.socket) {
            this.socket.close();
        }
    }
}
