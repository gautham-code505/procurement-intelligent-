import { state, subscribe } from './state.js';
import * as render from './render.js';
import { Demo } from './demo.js';
import * as api from './api.js';

let pollingInterval = null;

// Initialize
function init() {
    // Wire UI events
    setupUIControls();
    
    // Subscribe render function to state changes
    subscribe(() => render.render());

    // Initially render UI
    render.render();
}

function setupUIControls() {
    // Role selection
    document.getElementById('role-select').addEventListener('change', (e) => {
        state.currentRole = e.target.value;
        render.showToast(`Role changed to ${state.currentRole}`);
    });

    // Tabs
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            btn.classList.add('active');
            document.getElementById(btn.dataset.target).classList.add('active');
        });
    });

    // Demo Controls
    document.getElementById('btn-demo-start').addEventListener('click', async () => {
        // Disruption Injection
        await Demo.step2_Disruption();
    });

    document.getElementById('btn-demo-reset').addEventListener('click', async () => {
        stopPolling();
        await Demo.step0_Reset();
        startPolling();
    });

    // Modal Actions
    document.getElementById('btn-approve-rec').addEventListener('click', async () => {
        stopPolling(); // Pause background fetches while processing approval
        const success = await Demo.step5_Approve(true);
        if (success) {
            startPolling();
        } else {
            // Role failed or other error, resume polling anyway
            startPolling();
        }
    });
    
    document.getElementById('btn-reject-rec').addEventListener('click', async () => {
        stopPolling();
        await Demo.step5_Approve(false);
        startPolling();
    });

    // Farmer Search
    document.getElementById('btn-fetch-farmer').addEventListener('click', async () => {
        const fId = document.getElementById('farmer-id-input').value.trim();
        if (!fId) return;
        
        try {
            // Temporary role switch if testing as FARMER
            const isFarmer = state.currentRole === 'FARMER';
            
            const bookings = await api.getFarmerBookings(fId);
            if (bookings.length > 0) {
                // Find historical change if it exists
                const bkId = bookings[0].booking_id;
                const histChange = state.interventionHistory.find(c => c.booking_id === bkId);
                
                render.renderFarmerBooking(bookings[0], histChange);
            } else {
                render.showToast("No active bookings found for this farmer.", "info");
                document.getElementById('farmer-booking-details').classList.add('hidden');
            }
        } catch(err) {
            render.showToast(err.message, "error");
        }
    });
}

function startPolling() {
    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(() => {
        // Only poll if we are not blocked (e.g. not waiting on modal)
        if (state.demoStep === 1 || state.demoStep === 3 || state.demoStep === 7) {
            Demo.syncStateAndPrediction().then(() => render.render());
        }
    }, 2000);
}

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

// Start app
document.addEventListener('DOMContentLoaded', init);
