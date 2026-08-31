import { state, addTimelineEvent } from './state.js';
import * as api from './api.js';
import * as render from './render.js';

/**
 * 8-Step Deterministic Demo State Machine
 */
export const Demo = {
    // START / RESET
    async step0_Reset() {
        state.demoStep = 0;
        state.timeline = []; // clear timeline
        state.disruptedSnapshot = null;
        state.recoveredSnapshot = null;
        state.interventionHistory = [];
        state.activeRecommendation = null;
        
        // Base time for the demo: 2026-08-30T09:00:00 (as per the backend verification)
        state.simulatedTime = "2026-08-30T09:00:00";
        
        addTimelineEvent("Initializing Reset Sequence...", false);
        
        try {
            // Must be admin to reset
            const originalRole = state.currentRole;
            if (originalRole !== 'ADMIN') {
                render.showToast("Admin role required to reset. Temporarily using ADMIN.", "warning");
                state.currentRole = 'ADMIN';
            }
            
            const res = await api.resetDemo(state.simulatedTime);
            state.centreId = res.centre_id;
            
            state.currentRole = originalRole; // restore
            
            addTimelineEvent(`Reset Complete: Seeded ${res.bookings_seeded} bookings for centre ${state.centreId}`, false);
            
            // Move to step 1
            this.step1_SteadyState();
        } catch (err) {
            addTimelineEvent("Reset Failed: " + err.message, true);
            render.showToast("Reset Failed: " + err.message, "error");
        }
    },

    async step1_SteadyState() {
        state.demoStep = 1;
        addTimelineEvent("Entering Steady State.", false);
        await this.syncStateAndPrediction();
    },

    // DISRUPTION INJECT
    async step2_Disruption() {
        if (state.demoStep < 1) return render.showToast("Please Reset the Demo first.", "warning");
        
        state.demoStep = 2;
        // The script failure injected 2 events at 09:30:00
        state.simulatedTime = "2026-08-30T09:30:00";
        addTimelineEvent("Injecting Disruption Scenarios at " + state.simulatedTime, false);
        
        try {
            const originalRole = state.currentRole;
            state.currentRole = 'ADMIN';
            await api.runScenario(state.simulatedTime);
            state.currentRole = originalRole;
            
            addTimelineEvent("Disruption injected successfully.", false);
            
            // Move to congestion
            state.demoStep = 3;
            addTimelineEvent("Monitoring for congestion...", false);
        } catch(err) {
            addTimelineEvent("Disruption failed: " + err.message, true);
            render.showToast("Disruption Error: " + err.message, "error");
        }
    },
    
    // FETCH DURING POLLING LOOP
    async syncStateAndPrediction() {
        try {
            const st = await api.getCentreState(state.centreId);
            const pred = await api.getPredictions(state.centreId, state.simulatedTime);
            
            state.backendState = st;
            state.prediction = pred;
            
            // If we are in congestion step, save disrupted snapshot
            if (state.demoStep === 3) {
                if (!state.disruptedSnapshot && pred.congestion_level !== 'LOW') {
                    state.disruptedSnapshot = pred;
                    addTimelineEvent(`Congestion Detected: ${pred.congestion_level}`, true);
                }
            }
            
            // Check recommendations
            const recs = await api.getRecommendations(state.centreId);
            const pending = recs.filter(r => r.status === 'PENDING');
            if (pending.length > 0 && state.demoStep === 3) {
                state.demoStep = 4;
                state.activeRecommendation = pending[0];
                addTimelineEvent(`Recommendation ${state.activeRecommendation.recommendation_id} generated.`, false);
                render.showRecommendationModal(state.activeRecommendation);
            }
        } catch (err) {
            console.error("Sync Error", err);
        }
    },

    async step5_Approve(isApproved = true) {
        if (!state.activeRecommendation) return;
        
        state.demoStep = 5;
        // Freeze polling will be handled by app.js when this is called
        
        try {
            // Need ADMIN to approve
            if (state.currentRole !== 'ADMIN') {
                render.showToast("Role Error: Only ADMIN can approve recommendations.", "error");
                // Do not throw, just stop the flow
                return false; 
            }
            
            // Time moves forward slightly for approval processing
            state.simulatedTime = "2026-08-30T09:31:00";
            
            if (isApproved) {
                addTimelineEvent("Approving recommendation...", false);
                await api.approveRecommendation(state.activeRecommendation.recommendation_id, state.simulatedTime);
                addTimelineEvent("Recommendation APPROVED. Bookings rescheduled.", false);
                
                // Cache intervention history for Farmer View
                state.interventionHistory = state.activeRecommendation.changes;
                render.showToast("Intervention Approved successfully", "success");
            } else {
                addTimelineEvent("Rejecting recommendation...", false);
                await api.rejectRecommendation(state.activeRecommendation.recommendation_id);
                addTimelineEvent("Recommendation REJECTED.", false);
                render.showToast("Intervention Rejected", "info");
            }
            
            render.hideRecommendationModal();
            state.activeRecommendation = null;
            
            // Move to Step 6: Recovery Fetch
            await this.step6_Recovery();
            return true;
            
        } catch(err) {
            addTimelineEvent("Approval Failed: " + err.message, true);
            render.showToast(err.message, "error");
            return false;
        }
    },

    async step6_Recovery() {
        state.demoStep = 6;
        addTimelineEvent("Fetching post-intervention predictions...", false);
        
        // Immediate sync
        await this.syncStateAndPrediction();
        
        // Cache recovery snapshot
        state.recoveredSnapshot = state.prediction;
        addTimelineEvent(`Recovery prediction generated. Peak Queue: ${Math.max(...state.prediction.time_points.map(tp => tp.projected_queue))}`, false);
        
        state.demoStep = 7; // Complete
    }
};
