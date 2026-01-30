/**
 * Geolocation Capture with API Key Fallback - EasyMarket
 * Works with or without Google Maps API key configured
 *
 * @version 2.2.0
 * @author EasyMarket Team
 */

class GeolocationCapture {
    constructor() {
        this.watchId = null;
        this.currentPosition = null;
        this.accuracyThreshold = 90;
        this.maxWaitTime = 30000;
        this.startTime = null;
        this.isCapturing = false;
        this.permissionStatus = null;
        this.apiKeyConfigured = true; // Assume true until we find out otherwise

        this.elements = {
            gpsButton: document.getElementById('gpsLocationBtn'),
            manualButton: document.getElementById('manualLocationBtn'),
            gpsContainer: document.getElementById('gpsLocationContainer'),
            manualForm: document.getElementById('manualAddressForm'),
            accuracyIndicator: document.getElementById('accuracyIndicator'),
            accuracyValue: document.getElementById('accuracyValue'),
            accuracyStatus: document.getElementById('accuracyStatus'),
            latitudeInput: document.getElementById('latitude'),
            longitudeInput: document.getElementById('longitude'),
            accuracyInput: document.getElementById('location_accuracy'),
            locationMethodInput: document.getElementById('location_method'),
            confirmGpsBtn: document.getElementById('confirmGpsLocation'),
            cancelGpsBtn: document.getElementById('cancelGpsLocation'),
            gpsSpinner: document.getElementById('gpsSpinner'),
            gpsStatus: document.getElementById('gpsStatus'),
            debugInfo: document.getElementById('debugInfo')
        };

        this.init();
    }

    init() {
        // Check if geolocation is supported
        if (!navigator.geolocation) {
            this.showError('Geolocation is not supported by your browser. Please use a modern browser.');
            if (this.elements.gpsButton) {
                this.elements.gpsButton.disabled = true;
                this.elements.gpsButton.innerHTML = '<i class="fas fa-exclamation-triangle"></i> <span>GPS Not Available</span>';
            }
            return;
        }

        // Check HTTPS requirement
        this.checkHttpsRequirement();

        // Check permissions API support
        this.checkPermissions();

        // Bind event listeners
        if (this.elements.gpsButton) {
            this.elements.gpsButton.addEventListener('click', () => this.startGPSCapture());
        }

        if (this.elements.manualButton) {
            this.elements.manualButton.addEventListener('click', () => this.switchToManual());
        }

        if (this.elements.confirmGpsBtn) {
            this.elements.confirmGpsBtn.addEventListener('click', () => this.confirmLocation());
        }

        if (this.elements.cancelGpsBtn) {
            this.elements.cancelGpsBtn.addEventListener('click', () => this.cancelGPSCapture());
        }
    }

    checkHttpsRequirement() {
        const isSecure = window.location.protocol === 'https:' ||
                        window.location.hostname === 'localhost' ||
                        window.location.hostname === '127.0.0.1' ||
                        window.location.hostname.startsWith('192.168.');

        if (!isSecure) {
            this.showWarning(
                'GPS location requires HTTPS (secure connection). ' +
                'Location may not work properly. ' +
                'Please use: https://easymarket.vip'
            );
            this.logDebug('Not using HTTPS - geolocation may be blocked');
        } else {
            this.logDebug('HTTPS check passed');
        }
    }

    async checkPermissions() {
        if (!navigator.permissions) {
            this.logDebug('Permissions API not supported');
            return;
        }

        try {
            const result = await navigator.permissions.query({ name: 'geolocation' });
            this.permissionStatus = result.state;

            this.logDebug(`Permission status: ${result.state}`);

            if (result.state === 'denied') {
                this.showPermissionDeniedHelp();
            }

            result.addEventListener('change', () => {
                this.permissionStatus = result.state;
                this.logDebug(`Permission changed to: ${result.state}`);

                if (result.state === 'denied') {
                    this.showPermissionDeniedHelp();
                }
            });
        } catch (error) {
            this.logDebug(`Permission check error: ${error.message}`);
        }
    }

    showPermissionDeniedHelp() {
        const helpMessage = this.getBrowserSpecificHelp();
        this.showError(`Location access is blocked. ${helpMessage}`);
    }

    getBrowserSpecificHelp() {
        const userAgent = navigator.userAgent.toLowerCase();

        if (/iphone|ipad|ipod/.test(userAgent)) {
            return 'On iPhone/iPad: Settings → Safari → Location → Allow';
        } else if (/android/.test(userAgent)) {
            if (/chrome/.test(userAgent)) {
                return 'On Android Chrome: Tap the lock icon → Permissions → Location → Allow';
            } else if (/firefox/.test(userAgent)) {
                return 'On Android Firefox: Menu → Settings → Site Permissions → Location → Allow';
            } else {
                return 'On Android: Browser Settings → Site Settings → Location → Allow';
            }
        } else {
            return 'Please check your browser settings to allow location access.';
        }
    }

    startGPSCapture() {
        if (this.isCapturing) return;

        this.isCapturing = true;
        this.startTime = Date.now();

        // Update button states
        if (this.elements.gpsButton) {
            this.elements.gpsButton.classList.add('active');
        }
        if (this.elements.manualButton) {
            this.elements.manualButton.classList.remove('active');
        }

        // Show GPS container, hide manual form
        if (this.elements.gpsContainer) {
            this.elements.gpsContainer.classList.remove('d-none');
        }
        if (this.elements.manualForm) {
            this.elements.manualForm.classList.add('d-none');
        }

        // Show spinner and initial status
        this.updateStatus('Requesting GPS access...', 'info');
        this.showSpinner(true);
        this.logDebug('Starting GPS capture...');

        const options = {
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 0
        };

        // Try getCurrentPosition first
        navigator.geolocation.getCurrentPosition(
            (position) => {
                this.logDebug('Got initial position');
                this.handlePosition(position);

                // Then start watching for better accuracy
                this.watchId = navigator.geolocation.watchPosition(
                    (position) => this.handlePosition(position),
                    (error) => this.handleError(error),
                    options
                );
            },
            (error) => {
                this.logDebug('Initial position failed, trying watch...');
                this.watchId = navigator.geolocation.watchPosition(
                    (position) => this.handlePosition(position),
                    (error) => this.handleError(error),
                    options
                );
            },
            options
        );

        // Set timeout
        setTimeout(() => {
            if (this.isCapturing && !this.currentPosition) {
                this.cancelGPSCapture();
                this.showError(
                    'GPS signal timeout. This can happen if:\n' +
                    '• You\'re indoors or in area with poor GPS signal\n' +
                    '• Location services are disabled\n' +
                    '• Browser doesn\'t have permission\n\n' +
                    'Try moving outdoors or use manual entry.'
                );
            }
        }, this.maxWaitTime);
    }

    handlePosition(position) {
        this.currentPosition = position;
        const accuracy = position.coords.accuracy;
        const latitude = position.coords.latitude;
        const longitude = position.coords.longitude;

        this.logDebug(`Position: ${latitude}, ${longitude} (±${accuracy}m)`);

        // Update accuracy indicator
        this.updateAccuracyIndicator(accuracy);

        // Update hidden form fields
        if (this.elements.latitudeInput) {
            this.elements.latitudeInput.value = latitude.toFixed(8);
        }
        if (this.elements.longitudeInput) {
            this.elements.longitudeInput.value = longitude.toFixed(8);
        }
        if (this.elements.accuracyInput) {
            this.elements.accuracyInput.value = accuracy.toFixed(2);
        }
        if (this.elements.locationMethodInput) {
            this.elements.locationMethodInput.value = 'gps';
        }

        // Check if accuracy is good enough
        if (accuracy <= this.accuracyThreshold) {
            this.lockInLocation(accuracy);
        } else {
            this.updateStatus(
                `Improving accuracy... Current: ${Math.round(accuracy)}m`,
                'warning'
            );
        }
    }

    lockInLocation(accuracy) {
        this.showSpinner(false);

        this.updateStatus(
            `✓ Location locked! Accuracy: ${Math.round(accuracy)}m`,
            'success'
        );

        this.logDebug(`Location locked with ${accuracy}m accuracy`);

        // Enable confirm button
        if (this.elements.confirmGpsBtn) {
            this.elements.confirmGpsBtn.disabled = false;
            this.elements.confirmGpsBtn.classList.remove('btn-secondary');
            this.elements.confirmGpsBtn.classList.add('btn-success');
        }

        if (this.elements.accuracyIndicator) {
            this.elements.accuracyIndicator.classList.add('pulse');
            setTimeout(() => {
                this.elements.accuracyIndicator.classList.remove('pulse');
            }, 1000);
        }
    }

    updateAccuracyIndicator(accuracy) {
        if (!this.elements.accuracyIndicator) return;

        const percentage = Math.max(0, Math.min(100, 100 - (accuracy / 2)));
        const progressBar = this.elements.accuracyIndicator.querySelector('.progress-bar');

        if (progressBar) {
            progressBar.style.width = percentage + '%';
            progressBar.className = 'progress-bar';

            if (accuracy <= 20) {
                progressBar.classList.add('bg-success');
            } else if (accuracy <= 50) {
                progressBar.classList.add('bg-warning');
            } else {
                progressBar.classList.add('bg-danger');
            }
        }

        if (this.elements.accuracyValue) {
            this.elements.accuracyValue.textContent = `±${Math.round(accuracy)}m`;
        }

        if (this.elements.accuracyStatus) {
            let statusText = '';
            let statusClass = '';

            if (accuracy <= 20) {
                statusText = 'Excellent';
                statusClass = 'text-success';
            } else if (accuracy <= 50) {
                statusText = 'Good';
                statusClass = 'text-warning';
            } else if (accuracy <= 100) {
                statusText = 'Fair';
                statusClass = 'text-warning';
            } else {
                statusText = 'Poor';
                statusClass = 'text-danger';
            }

            this.elements.accuracyStatus.textContent = statusText;
            this.elements.accuracyStatus.className = `fw-bold ${statusClass}`;
        }
    }

    handleError(error) {
        this.logDebug(`Geolocation error: ${error.code} - ${error.message}`);

        let message = '';
        let helpText = '';

        switch (error.code) {
            case error.PERMISSION_DENIED:
                message = 'Location access was denied.';
                helpText = this.getBrowserSpecificHelp();
                this.showError(`${message}\n\n${helpText}`);
                break;

            case error.POSITION_UNAVAILABLE:
                message = 'Location unavailable. GPS may be turned off or you\'re in an area with no signal.';
                this.showError(message);
                break;

            case error.TIMEOUT:
                message = 'Location request timed out. Try again or move to area with better signal.';
                this.showError(message);
                break;

            default:
                message = 'Unknown error getting location.';
                this.showError(message);
        }

        this.cancelGPSCapture();
    }

    confirmLocation() {
        if (!this.currentPosition) {
            this.showError('No location captured yet');
            return;
        }

        this.logDebug('Confirming location, starting reverse geocode...');

        this.reverseGeocode(
            this.currentPosition.coords.latitude,
            this.currentPosition.coords.longitude
        );
    }

    reverseGeocode(lat, lng) {
        this.updateStatus('Getting address from coordinates...', 'info');
        this.showSpinner(true);

        fetch('/orders/api/reverse-geocode/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCSRFToken()
            },
            body: JSON.stringify({
                latitude: lat,
                longitude: lng
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            this.logDebug(`Reverse geocode response: ${JSON.stringify(data)}`);

            if (data.success) {
                // Check if in fallback mode (API key not configured)
                if (data.fallback_mode) {
                    this.apiKeyConfigured = false;
                    this.showInfo(
                        'GPS coordinates captured successfully! ' +
                        (data.note || 'Address lookup unavailable, but coordinates will be used for delivery.')
                    );
                } else {
                    this.showSuccess('Location captured successfully! Please review your address.');
                }

                // Populate address fields
                this.populateAddressFields(data.address);

                // Hide GPS container, show manual form
                if (this.elements.gpsContainer) {
                    this.elements.gpsContainer.classList.add('d-none');
                }
                if (this.elements.manualForm) {
                    this.elements.manualForm.classList.remove('d-none');
                }

                // Update button states
                if (this.elements.manualButton) {
                    this.elements.manualButton.classList.add('active');
                }
                if (this.elements.gpsButton) {
                    this.elements.gpsButton.classList.remove('active');
                }

                this.stopCapture();
            } else {
                // Check if it's a service unavailable error (API key issue)
                if (data.fallback) {
                    this.showWarning(
                        data.error + '\n\n' +
                        'You can still save GPS coordinates for delivery, but address lookup is unavailable.'
                    );
                    this.apiKeyConfigured = false;

                    // Use coordinates as address
                    this.populateAddressFields({
                        street: `GPS: ${lat.toFixed(6)}, ${lng.toFixed(6)}`,
                        city: '',
                        region: '',
                        postal_code: '',
                        country: 'The Gambia'
                    });

                    // Show form anyway
                    if (this.elements.gpsContainer) {
                        this.elements.gpsContainer.classList.add('d-none');
                    }
                    if (this.elements.manualForm) {
                        this.elements.manualForm.classList.remove('d-none');
                    }

                    this.stopCapture();
                } else {
                    this.showError(data.error || 'Failed to get address from coordinates');
                    this.showSpinner(false);
                }
            }
        })
        .catch(error => {
            this.logDebug(`Reverse geocode error: ${error.message}`);
            this.showError('Failed to connect to geocoding service. Using coordinates only.');

            // Fallback: use coordinates as address
            this.populateAddressFields({
                street: `GPS: ${lat.toFixed(6)}, ${lng.toFixed(6)}`,
                city: '',
                region: '',
                postal_code: '',
                country: 'The Gambia'
            });

            if (this.elements.gpsContainer) {
                this.elements.gpsContainer.classList.add('d-none');
            }
            if (this.elements.manualForm) {
                this.elements.manualForm.classList.remove('d-none');
            }

            this.stopCapture();
            this.showSpinner(false);
        });
    }

    populateAddressFields(address) {
        const fields = {
            'new_street': address.street || '',
            'new_city': address.city || '',
            'new_region': address.region || '',
            'new_geo_code': address.postal_code || '',
            'new_country': address.country || 'The Gambia'
        };

        for (const [fieldName, value] of Object.entries(fields)) {
            const field = document.querySelector(`[name="${fieldName}"]`);
            if (field && value) {
                field.value = value;
            }
        }

        const geocodedAddressField = document.getElementById('geocoded_address');
        if (geocodedAddressField) {
            geocodedAddressField.value = address.formatted_address || '';
        }

        const isGambiaField = document.getElementById('is_gambia');
        if (isGambiaField && address.is_gambia !== undefined) {
            isGambiaField.value = address.is_gambia ? 'true' : 'false';
            this.showGambiaIndicator(address.is_gambia);
        }
    }

    showGambiaIndicator(isGambia) {
        const indicator = document.getElementById('gambiaIndicator');
        if (!indicator) return;

        indicator.classList.remove('d-none');
        if (isGambia) {
            indicator.className = 'gambia-indicator in-gambia';
            indicator.innerHTML = '<i class="fas fa-check-circle me-2"></i>Location verified in The Gambia';
        } else {
            indicator.className = 'gambia-indicator outside-gambia';
            indicator.innerHTML = '<i class="fas fa-info-circle me-2"></i>Location outside The Gambia';
        }
    }

    switchToManual() {
        this.cancelGPSCapture();

        if (this.elements.manualButton) {
            this.elements.manualButton.classList.add('active');
        }
        if (this.elements.gpsButton) {
            this.elements.gpsButton.classList.remove('active');
        }

        if (this.elements.gpsContainer) {
            this.elements.gpsContainer.classList.add('d-none');
        }
        if (this.elements.manualForm) {
            this.elements.manualForm.classList.remove('d-none');
        }
    }

    cancelGPSCapture() {
        this.stopCapture();

        if (this.elements.confirmGpsBtn) {
            this.elements.confirmGpsBtn.disabled = true;
            this.elements.confirmGpsBtn.classList.remove('btn-success');
            this.elements.confirmGpsBtn.classList.add('btn-secondary');
        }

        this.updateStatus('', 'info');
        this.showSpinner(false);

        if (this.elements.accuracyIndicator) {
            const progressBar = this.elements.accuracyIndicator.querySelector('.progress-bar');
            if (progressBar) {
                progressBar.style.width = '0%';
            }
        }
        if (this.elements.accuracyValue) {
            this.elements.accuracyValue.textContent = 'Waiting...';
        }
        if (this.elements.accuracyStatus) {
            this.elements.accuracyStatus.textContent = 'Initializing GPS...';
            this.elements.accuracyStatus.className = 'text-muted';
        }
    }

    stopCapture() {
        if (this.watchId !== null) {
            navigator.geolocation.clearWatch(this.watchId);
            this.watchId = null;
        }
        this.isCapturing = false;
        this.currentPosition = null;
    }

    updateStatus(message, type = 'info') {
        if (!this.elements.gpsStatus) return;
        this.elements.gpsStatus.textContent = message;
        this.elements.gpsStatus.className = `text-${type}`;
    }

    showSpinner(show) {
        if (!this.elements.gpsSpinner) return;
        if (show) {
            this.elements.gpsSpinner.classList.remove('d-none');
        } else {
            this.elements.gpsSpinner.classList.add('d-none');
        }
    }

    showError(message) {
        this.createAlert('danger', 'Location Error', message, 15000);
    }

    showWarning(message) {
        this.createAlert('warning', 'Warning', message, 10000);
    }

    showSuccess(message) {
        this.createAlert('success', 'Success', message, 6000);
    }

    showInfo(message) {
        this.createAlert('info', 'Info', message, 8000);
    }

    createAlert(type, title, message, duration) {
        const iconMap = {
            danger: 'exclamation-triangle',
            warning: 'exclamation-circle',
            success: 'check-circle',
            info: 'info-circle'
        };

        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type} alert-dismissible fade show mt-3`;
        alertDiv.style.whiteSpace = 'pre-line';
        alertDiv.innerHTML = `
            <i class="fas fa-${iconMap[type]} me-2"></i>
            <strong>${title}</strong><br>
            <small>${message}</small>
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        const container = document.getElementById('newAddressForm') || document.body;
        container.insertBefore(alertDiv, container.firstChild);

        setTimeout(() => {
            alertDiv.remove();
        }, duration);
    }

    logDebug(message) {
        console.log(`[Geolocation] ${message}`);

        if (this.elements.debugInfo) {
            const time = new Date().toLocaleTimeString();
            const line = document.createElement('div');
            line.textContent = `[${time}] ${message}`;
            line.style.fontSize = '11px';
            line.style.marginBottom = '2px';
            this.elements.debugInfo.appendChild(line);

            while (this.elements.debugInfo.children.length > 10) {
                this.elements.debugInfo.removeChild(this.elements.debugInfo.firstChild);
            }
        }
    }

    getCSRFToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.geoCapture = new GeolocationCapture();
});

// Geocode postal code when entered
function geocodePostalCode() {
    const postalCodeInput = document.querySelector('[name="new_geo_code"]');
    if (!postalCodeInput || !postalCodeInput.value) return;

    const postalCode = postalCodeInput.value.trim();
    if (postalCode.length < 2) return;

    fetch('/orders/api/geocode/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || ''
        },
        body: JSON.stringify({
            postal_code: postalCode,
            country: 'Gambia'
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const gambiaIndicator = document.getElementById('gambiaIndicator');
            if (gambiaIndicator) {
                gambiaIndicator.classList.remove('d-none');
                if (data.is_gambia) {
                    gambiaIndicator.className = 'gambia-indicator in-gambia';
                    gambiaIndicator.innerHTML = '<i class="fas fa-check-circle me-2"></i>Location verified in The Gambia';
                } else {
                    gambiaIndicator.className = 'gambia-indicator outside-gambia';
                    gambiaIndicator.innerHTML = '<i class="fas fa-info-circle me-2"></i>Location outside The Gambia';
                }
            }

            if (data.location) {
                const latField = document.getElementById('latitude');
                const lngField = document.getElementById('longitude');
                const methodField = document.getElementById('location_method');

                if (latField) latField.value = data.location.lat;
                if (lngField) lngField.value = data.location.lng;
                if (methodField) methodField.value = 'geocoded';
            }
        } else if (data.fallback) {
            console.log('Postal code geocoding unavailable:', data.error);
            // Silently fail - postal code geocoding is optional
        }
    })
    .catch(error => {
        console.error('Geocoding error:', error);
        // Silently fail - postal code geocoding is optional
    });
}