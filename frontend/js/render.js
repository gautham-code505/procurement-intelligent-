import { state } from './state.js';

function getEl(id) {
    return document.getElementById(id);
}

// ----------------------------------------------------
// TOAST NOTIFICATIONS
// ----------------------------------------------------
export function showToast(message, type = 'info') {
    const container = getEl('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'fadeIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// ----------------------------------------------------
// MAIN RENDER FUNCTION
// ----------------------------------------------------
export function render() {
    renderDemoStatus();
    renderOperatorDashboard();
    renderImpactPanel();
    renderTimeline();
}

function renderDemoStatus() {
    const steps = [
        "STEP 0: IDLE / RESET",
        "STEP 1: STEADY STATE",
        "STEP 2: DISRUPTION",
        "STEP 3: CONGESTION",
        "STEP 4: RECOMMENDATION",
        "STEP 5: APPROVING...",
        "STEP 6: RECOVERY",
        "STEP 7: COMPLETE"
    ];
    
    const indicator = getEl('demo-status-indicator');
    if (state.demoStep >= 0 && state.demoStep < steps.length) {
        indicator.textContent = steps[state.demoStep];
    }
}

function renderOperatorDashboard() {
    if (!state.backendState) return;

    // Top Strip
    getEl('stat-counters').textContent = state.backendState.active_counters;
    getEl('stat-capacity').textContent = state.backendState.effective_processing_rate + ' /hr';
    
    // Counters Grid
    const countersContainer = getEl('counters-container');
    countersContainer.innerHTML = '';
    for (const c of state.backendState.counters) {
        const isUnavailable = c.status === 'UNAVAILABLE';
        const div = document.createElement('div');
        div.className = `counter-box ${isUnavailable ? 'unavailable' : ''}`;
        div.innerHTML = `
            <div class="counter-name">${c.counter_id.toUpperCase()}</div>
            <div class="badge ${isUnavailable ? 'danger' : 'success'}">${c.status}</div>
            <div class="counter-rate">${c.processing_rate}/hr</div>
        `;
        countersContainer.appendChild(div);
    }

    if (state.prediction) {
        const maxQ = Math.max(...state.prediction.time_points.map(tp => tp.projected_queue));
        const maxW = Math.max(...state.prediction.time_points.map(tp => tp.estimated_wait_minutes));
        
        getEl('stat-queue').textContent = maxQ;
        getEl('pred-peak-queue').textContent = maxQ;
        getEl('pred-peak-wait').textContent = maxW.toFixed(1) + 'm';
        
        const congestionEl = getEl('stat-congestion');
        congestionEl.textContent = state.prediction.congestion_level;
        congestionEl.className = 'stat-value congestion-badge';
        
        let cColor = 'var(--color-success)';
        if (state.prediction.congestion_level === 'MEDIUM') cColor = 'var(--color-warning)';
        if (state.prediction.congestion_level === 'HIGH' || state.prediction.congestion_level === 'CRITICAL') cColor = 'var(--color-danger)';
        congestionEl.style.color = cColor;
        
        renderGraph(state.prediction.time_points, cColor);
    }
}

function renderGraph(timePoints, color) {
    const graphContainer = getEl('queue-graph');
    graphContainer.innerHTML = '';
    
    if (!timePoints || timePoints.length === 0) return;
    
    const maxQ = Math.max(10, ...timePoints.map(t => t.projected_queue)); // min scale 10
    
    timePoints.forEach(tp => {
        const bar = document.createElement('div');
        bar.className = 'graph-bar';
        const heightPct = (tp.projected_queue / maxQ) * 100;
        bar.style.height = `${heightPct}%`;
        bar.style.backgroundColor = color;
        bar.title = `Queue: ${tp.projected_queue} | Wait: ${tp.estimated_wait_minutes.toFixed(1)}m`;
        graphContainer.appendChild(bar);
    });
}

function renderImpactPanel() {
    // Disrupted
    if (state.disruptedSnapshot) {
        const maxQ = Math.max(...state.disruptedSnapshot.time_points.map(tp => tp.projected_queue));
        const maxW = Math.max(...state.disruptedSnapshot.time_points.map(tp => tp.estimated_wait_minutes));
        getEl('impact-disrupted-queue').textContent = maxQ;
        getEl('impact-disrupted-wait').textContent = maxW.toFixed(1) + 'm';
    } else {
        getEl('impact-disrupted-queue').textContent = '--';
        getEl('impact-disrupted-wait').textContent = '--';
    }

    // Recovered
    if (state.recoveredSnapshot) {
        const maxQ = Math.max(...state.recoveredSnapshot.time_points.map(tp => tp.projected_queue));
        const maxW = Math.max(...state.recoveredSnapshot.time_points.map(tp => tp.estimated_wait_minutes));
        getEl('impact-recovered-queue').textContent = maxQ;
        getEl('impact-recovered-wait').textContent = maxW.toFixed(1) + 'm';
        
        // Calculate Deltas
        if (state.disruptedSnapshot) {
            const dq = Math.max(...state.disruptedSnapshot.time_points.map(tp => tp.projected_queue));
            const dw = Math.max(...state.disruptedSnapshot.time_points.map(tp => tp.estimated_wait_minutes));
            
            const deltaQ = dq - maxQ;
            const deltaW = dw - maxW;
            const affected = state.activeRecommendation ? state.activeRecommendation.changes.length : 0;
            
            const deltaEl = getEl('impact-delta');
            deltaEl.innerHTML = `Queue reduced by ${deltaQ} | Wait reduced by ${deltaW.toFixed(1)}m<br/><small style="font-weight:normal;color:var(--text-secondary)">Affected Bookings: ${affected}</small>`;
        }
    } else {
        getEl('impact-recovered-queue').textContent = '--';
        getEl('impact-recovered-wait').textContent = '--';
        getEl('impact-delta').innerHTML = '';
    }
}

function renderTimeline() {
    const container = getEl('event-timeline');
    container.innerHTML = '';
    state.timeline.forEach(t => {
        const el = document.createElement('div');
        el.className = 'timeline-item';
        if (t.isError) el.style.borderLeftColor = 'var(--color-danger)';
        el.innerHTML = `
            <div class="timeline-time">${t.time}</div>
            <div>${t.message}</div>
        `;
        container.appendChild(el);
    });
}

// ----------------------------------------------------
// MODAL & FARMER ACTIONS
// ----------------------------------------------------

export function showRecommendationModal(rec) {
    getEl('rec-reason').textContent = rec.reason;
    getEl('rec-impact').textContent = rec.expected_impact;
    
    // Parse constraints if JSON
    let cCheck = rec.constraint_check;
    try { cCheck = JSON.stringify(JSON.parse(cCheck), null, 2); } catch(e) {}
    getEl('rec-constraint-check').textContent = cCheck;
    
    let fCheck = rec.fairness_check;
    try { fCheck = JSON.stringify(JSON.parse(fCheck), null, 2); } catch(e) {}
    getEl('rec-fairness-check').textContent = fCheck;
    
    const changes = rec.changes || [];
    getEl('rec-changes-count').textContent = changes.length;
    
    const tbody = getEl('rec-changes-table').querySelector('tbody');
    tbody.innerHTML = '';
    changes.forEach(ch => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${ch.booking_id}</td>
            <td>${formatDate(ch.original_start)}</td>
            <td>${formatDate(ch.proposed_start)}</td>
        `;
        tbody.appendChild(row);
    });
    
    getEl('recommendation-modal').classList.remove('hidden');
}

export function hideRecommendationModal() {
    getEl('recommendation-modal').classList.add('hidden');
}

export function renderFarmerBooking(liveBooking, historicalChange = null) {
    const container = getEl('farmer-booking-details');
    container.classList.remove('hidden');
    
    // Live Data
    getEl('fb-id').textContent = liveBooking.booking_id;
    const stateEl = getEl('fb-state');
    stateEl.textContent = liveBooking.booking_state;
    stateEl.className = 'badge ' + (liveBooking.booking_state === 'RESCHEDULED' ? 'warning' : 'success');
    getEl('fb-slot').textContent = formatDate(liveBooking.scheduled_start_time);
    getEl('fb-reschedules').textContent = liveBooking.reschedule_count;
    getEl('fb-procurement').textContent = liveBooking.procurement_status;
    getEl('fb-payment').textContent = liveBooking.payment_status;
    
    // Intervention History
    const historyContainer = getEl('farmer-intervention-history');
    if (historicalChange && liveBooking.booking_state === 'RESCHEDULED') {
        historyContainer.classList.remove('hidden');
        getEl('fb-original-slot').textContent = formatDate(historicalChange.original_start);
    } else {
        historyContainer.classList.add('hidden');
    }
}

function formatDate(isoStr) {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
}
