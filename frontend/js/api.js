import { state } from './state.js';

const API_BASE = '/api';

/**
 * Core fetch wrapper adding headers and error handling
 */
async function fetchAPI(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        'X-User-Role': state.currentRole,
        ...(options.headers || {})
    };

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });
        let data = null;
        
        // Handle no-content or JSON responses
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            data = await response.json();
        }

        if (!response.ok) {
            const errorMsg = data && data.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : `HTTP ${response.status}`;
            throw new Error(errorMsg);
        }

        return data;
    } catch (error) {
        throw error;
    }
}

// ----------------------------------------------------
// SCENARIOS & DEMO
// ----------------------------------------------------

export async function resetDemo(simulatedTime) {
    return await fetchAPI(`/scenarios/reset?simulated_time=${encodeURIComponent(simulatedTime)}`, { method: 'POST' });
}

export async function runScenario(simulatedTime) {
    return await fetchAPI(`/scenarios/run?simulated_time=${encodeURIComponent(simulatedTime)}`, { method: 'POST' });
}

// ----------------------------------------------------
// STATE & PREDICTIONS
// ----------------------------------------------------

export async function getCentreState(centreId) {
    return await fetchAPI(`/centres/${centreId}/state`, { method: 'GET' });
}

export async function getPredictions(centreId, simulatedTime) {
    return await fetchAPI(`/centres/${centreId}/predictions?simulated_time=${encodeURIComponent(simulatedTime)}`, { method: 'GET' });
}

// ----------------------------------------------------
// RECOMMENDATIONS
// ----------------------------------------------------

export async function getRecommendations(centreId) {
    return await fetchAPI(`/centres/${centreId}/recommendations`, { method: 'GET' });
}

export async function approveRecommendation(recId, simulatedTime) {
    return await fetchAPI(`/recommendations/${recId}/approve?simulated_time=${encodeURIComponent(simulatedTime)}`, { method: 'POST' });
}

export async function rejectRecommendation(recId) {
    return await fetchAPI(`/recommendations/${recId}/reject`, { method: 'POST' });
}

// ----------------------------------------------------
// FARMER
// ----------------------------------------------------

export async function getFarmerBookings(farmerId) {
    return await fetchAPI(`/farmers/${farmerId}/bookings`, { method: 'GET' });
}
