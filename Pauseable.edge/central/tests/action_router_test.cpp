#include <cassert>
#include <chrono>
#include <filesystem>
#include <iostream>

#include <nlohmann/json.hpp>

#include "ActionRouter.hpp"
#include "BehaviorInference.hpp"
#include "DecisionEvent.hpp"

namespace {

pauseable::Decision decision(
    std::string eventId,
    pauseable::DecisionType type,
    pauseable::RiskLevel risk,
    std::string source)
{
    pauseable::Decision value;
    value.eventId = std::move(eventId);
    value.type = type;
    value.risk = risk;
    value.source = std::move(source);
    value.occurredAt = "2026-09-20T08:00:00Z";
    value.riskScore = risk == pauseable::RiskLevel::Normal
        ? std::optional<int>(0) : std::optional<int>(65);
    value.patternCode = "repeated_appliance_use";
    value.message = "test message";
    return value;
}

}

int main()
{
    using namespace std::chrono;
    const auto root = std::filesystem::temp_directory_path() / "pauseable-action-router-test";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);
    const auto now = system_clock::time_point(seconds(1'800'000'000));

    pauseable::ActionRouterConfig disabledConfig;
    disabledConfig.statePath = (root / "disabled.json").string();
    pauseable::ActionRouter disabled(disabledConfig);
    const auto blocked = disabled.route(decision(
        "evt-disabled", pauseable::DecisionType::RepetitiveBehavior,
        pauseable::RiskLevel::Caution, "repetitive-ai"), now);
    assert(blocked.disposition == pauseable::ActionDisposition::Blocked);
    assert(blocked.reason == "source_actions_disabled");

    pauseable::ActionRouterConfig config;
    config.repetitiveActionsEnabled = true;
    config.wanderingActionsEnabled = true;
    config.repetitiveCooldown = seconds(600);
    config.wanderingCooldown = seconds(120);
    config.statePath = (root / "state.json").string();
    pauseable::ActionRouter router(config);

    const auto first = router.route(decision(
        "evt-1", pauseable::DecisionType::RepetitiveBehavior,
        pauseable::RiskLevel::Caution, "repetitive-ai"), now);
    assert(first.disposition == pauseable::ActionDisposition::Execute);
    assert(first.notifyGuardian && first.speakLocal && !first.controlAppliance);
    assert(first.reason == "first_risk_event");

    const auto sameEventRetry = router.route(decision(
        "evt-1", pauseable::DecisionType::RepetitiveBehavior,
        pauseable::RiskLevel::Caution, "repetitive-ai"), now + seconds(1));
    assert(sameEventRetry.disposition == pauseable::ActionDisposition::Execute);
    assert(sameEventRetry.notifyGuardian && !sameEventRetry.speakLocal);
    assert(sameEventRetry.reason == "same_event_retry");

    const auto suppressed = router.route(decision(
        "evt-2", pauseable::DecisionType::RepetitiveBehavior,
        pauseable::RiskLevel::Caution, "repetitive-ai"), now + seconds(60));
    assert(suppressed.disposition == pauseable::ActionDisposition::Suppressed);
    assert(suppressed.reason == "cooldown_active");

    const auto escalated = router.route(decision(
        "evt-3", pauseable::DecisionType::RepetitiveBehavior,
        pauseable::RiskLevel::Danger, "repetitive-ai"), now + seconds(90));
    assert(escalated.disposition == pauseable::ActionDisposition::Execute);
    assert(escalated.reason == "risk_escalated");

    const auto reminder = router.route(decision(
        "evt-4", pauseable::DecisionType::RepetitiveBehavior,
        pauseable::RiskLevel::Danger, "repetitive-ai"), now + seconds(700));
    assert(reminder.disposition == pauseable::ActionDisposition::Execute);
    assert(reminder.reason == "cooldown_elapsed");

    const auto mismatch = router.route(decision(
        "evt-mismatch", pauseable::DecisionType::WanderingSuspected,
        pauseable::RiskLevel::Caution, "repetitive-ai"), now);
    assert(mismatch.disposition == pauseable::ActionDisposition::Blocked);
    assert(mismatch.reason == "source_decision_mismatch");

    pauseable::ActionRouter restored(config);
    const auto persistedSuppression = restored.route(decision(
        "evt-5", pauseable::DecisionType::RepetitiveBehavior,
        pauseable::RiskLevel::Danger, "repetitive-ai"), now + seconds(710));
    assert(persistedSuppression.disposition == pauseable::ActionDisposition::Suppressed);

    pauseable::ActionRouterConfig recoveryConfig = config;
    recoveryConfig.recoveryNotificationsEnabled = true;
    recoveryConfig.statePath = (root / "recovery.json").string();
    pauseable::ActionRouter recoveryRouter(recoveryConfig);
    recoveryRouter.route(decision(
        "evt-risk", pauseable::DecisionType::WanderingSuspected,
        pauseable::RiskLevel::Danger, "wandering-ai"), now);
    const auto recovery = recoveryRouter.route(decision(
        "evt-recovery", pauseable::DecisionType::Normal,
        pauseable::RiskLevel::Normal, "wandering-ai"), now + seconds(10));
    assert(recovery.disposition == pauseable::ActionDisposition::Execute);
    assert(recovery.notifyGuardian && !recovery.speakLocal);
    assert(recovery.reason == "normal_recovery");

    pauseable::BehaviorInference inference;
    inference.patientId = "byunwoojin";
    inference.deviceId = "pi5-home-01";
    const auto payload = nlohmann::json::parse(
        pauseable::makeDecisionEventPayload(inference, first));
    assert(payload.at("event_id") == "evt-1");
    assert(payload.at("source") == "central-atlas-app");
    assert(payload.at("decision") == "repetitive_behavior");
    assert(payload.at("actions").size() == 1);
    assert(payload.at("actions").at(0) == "notify_guardian");
    assert(payload.at("pattern_code") == "repeated_appliance_use");

    std::filesystem::remove_all(root);
    std::cout << "action_router_test passed\n";
    return 0;
}
