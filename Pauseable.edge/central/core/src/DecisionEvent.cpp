#include "DecisionEvent.hpp"

#include <nlohmann/json.hpp>

namespace pauseable {

std::string makeDecisionEventPayload(
    const BehaviorInference& inference,
    const ActionPlan& plan)
{
    nlohmann::json actions = nlohmann::json::array();
    if (plan.notifyGuardian) actions.push_back("notify_guardian");
    if (plan.controlAppliance) actions.push_back("control_appliance");

    nlohmann::json payload{
        {"contract_version", "1.0"},
        {"event_id", plan.decision.eventId},
        {"occurred_at", plan.decision.occurredAt},
        {"patient_id", inference.patientId},
        {"device_id", inference.deviceId},
        {"source", "central-atlas-app"},
        {"decision", toString(plan.decision.type)},
        {"risk_level", toString(plan.decision.risk)},
        {"risk_score", plan.decision.riskScore
            ? nlohmann::json(*plan.decision.riskScore)
            : nlohmann::json(nullptr)},
        {"message", plan.decision.message},
        {"actions", std::move(actions)}};

    if (!plan.decision.patternCode.empty()) {
        payload["pattern_code"] = plan.decision.patternCode;
    }
    return payload.dump();
}

}
