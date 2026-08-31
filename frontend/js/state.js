// State is the single source of truth for the frontend UI.
export const state = {
    // Current role selected in UI (ADMIN, OPERATOR, FARMER)
    currentRole: 'ADMIN',
    
    // The simulated time managed by the demo state machine
    simulatedTime: null,
    
    // Current Centre ID (retrieved from /reset)
    centreId: 'c1', // default per demo.json
    
    // Latest backend state
    backendState: null,
    
    // Latest prediction
    prediction: null,
    
    // Disruption and Recovery tracking
    disruptedSnapshot: null,
    recoveredSnapshot: null,
    
    // Pending recommendation
    activeRecommendation: null,
    
    // Intervention History (cache of approved recommendation changes)
    interventionHistory: [],
    
    // Demo Mode Status
    demoStep: 0,
    
    // Timeline events
    timeline: []
};

// Simple event system to trigger UI re-renders
const listeners = [];

export function subscribe(listener) {
    listeners.push(listener);
}

export function notify() {
    for (const listener of listeners) {
        listener(state);
    }
}

export function addTimelineEvent(message, isError = false) {
    const timeStr = state.simulatedTime ? new Date(state.simulatedTime).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'}) : 'Init';
    state.timeline.unshift({ time: timeStr, message, isError });
    if (state.timeline.length > 50) state.timeline.pop();
    notify();
}
