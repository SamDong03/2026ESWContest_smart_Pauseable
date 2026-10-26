#include "BehaviorInference.hpp"

#include <cassert>
#include <chrono>
#include <ctime>
#include <filesystem>
#include <iostream>
#include <limits>
#include <string>

#include <nlohmann/json.hpp>

namespace {

std::chrono::system_clock::time_point utc(
    int year, int month, int day, int hour, int minute, int second)
{
    std::tm value{};
    value.tm_year = year - 1900;
    value.tm_mon = month - 1;
    value.tm_mday = day;
    value.tm_hour = hour;
    value.tm_min = minute;
    value.tm_sec = second;
#ifdef _WIN32
    return std::chrono::system_clock::from_time_t(_mkgmtime(&value));
#else
    return std::chrono::system_clock::from_time_t(timegm(&value));
#endif
}

nlohmann::json repetitivePayload()
{
    return {
        {"contract_version", "1.0"},
        {"event_id", "evt-repetitive-test-1"},
        {"occurred_at", "2026-09-20T08:00:00Z"},
        {"patient_id", "byunwoojin"},
        {"device_id", "pi5-home-01"},
        {"source", "repetitive-ai"},
        {"behavior", "repetitive"},
        {"risk_level", "caution"},
        {"risk_score", 62},
        {"model_version", "ha-hybrid-v1"},
        {"inference_status", "ok"},
        {"evidence", {
            {"window_seconds", 600},
            {"observation_count", 14},
            {"pattern_code", "repeated_door_use"},
            {"reason_text", "Repeated state transitions exceeded the personal baseline."},
            {"decision_policy", "rules_with_shadow_models"},
            {"model_status", "baseline_active"},
            {"reason_codes", {"repeated_transition"}}
        }}
    };
}

}

int main()
{
    const pauseable::BehaviorValidationConfig config;
    const auto now = utc(2026, 9, 20, 8, 2, 0);

    const auto repetitive = repetitivePayload();
    const auto accepted = pauseable::validateBehaviorInference(
        "pauseable/ai/repetitive/decision", repetitive.dump(), config, now);
    assert(accepted.disposition == pauseable::ValidationDisposition::Accepted);
    assert(accepted.inference->source == pauseable::BehaviorSource::RepetitiveAi);
    assert(accepted.inference->behavior == pauseable::BehaviorType::Repetitive);
    const auto decision = pauseable::toDecision(*accepted.inference);
    assert(decision.type == pauseable::DecisionType::RepetitiveBehavior);
    assert(decision.risk == pauseable::RiskLevel::Caution);
    assert(decision.riskScore == 62);
    assert(decision.patternCode == "repeated_door_use");

    auto wandering = repetitive;
    wandering["event_id"] = "evt-wandering-test-1";
    wandering["source"] = "wandering-ai";
    wandering["behavior"] = "wandering";
    wandering["evidence"]["pattern_code"] = "shape_review_candidate";
    wandering["evidence"]["model_status"] = "research_review_only";
    const auto wanderingAccepted = pauseable::validateBehaviorInference(
        "pauseable/ai/wandering/decision", wandering.dump(), config, now);
    assert(wanderingAccepted.disposition == pauseable::ValidationDisposition::Accepted);
    assert(pauseable::toDecision(*wanderingAccepted.inference).type ==
           pauseable::DecisionType::WanderingSuspected);

    const auto topicMismatch = pauseable::validateBehaviorInference(
        "pauseable/ai/repetitive/decision", wandering.dump(), config, now);
    assert(topicMismatch.disposition == pauseable::ValidationDisposition::TopicMismatch);

    const auto stale = pauseable::validateBehaviorInference(
        "pauseable/ai/repetitive/decision", repetitive.dump(), config,
        utc(2026, 9, 20, 8, 5, 1));
    assert(stale.disposition == pauseable::ValidationDisposition::StaleEvent);

    auto future = repetitive;
    future["occurred_at"] = "2026-09-20T08:02:31Z";
    const auto futureResult = pauseable::validateBehaviorInference(
        "pauseable/ai/repetitive/decision", future.dump(), config, now);
    assert(futureResult.disposition == pauseable::ValidationDisposition::FutureEvent);

    auto invalidUnknown = repetitive;
    invalidUnknown["inference_status"] = "sensor_error";
    const auto invalidUnknownResult = pauseable::validateBehaviorInference(
        "pauseable/ai/repetitive/decision", invalidUnknown.dump(), config, now);
    assert(invalidUnknownResult.disposition == pauseable::ValidationDisposition::InvalidSchema);

    auto validUnknown = invalidUnknown;
    validUnknown["behavior"] = "unknown";
    validUnknown["risk_level"] = "unknown";
    validUnknown["risk_score"] = nullptr;
    const auto validUnknownResult = pauseable::validateBehaviorInference(
        "pauseable/ai/repetitive/decision", validUnknown.dump(), config, now);
    assert(validUnknownResult.disposition == pauseable::ValidationDisposition::Accepted);
    assert(pauseable::toDecision(*validUnknownResult.inference).type ==
           pauseable::DecisionType::Unknown);

    auto extraField = repetitive;
    extraField["unexpected"] = true;
    const auto extraFieldResult = pauseable::validateBehaviorInference(
        "pauseable/ai/repetitive/decision", extraField.dump(), config, now);
    assert(extraFieldResult.disposition == pauseable::ValidationDisposition::InvalidSchema);

    auto invalidPattern = repetitive;
    invalidPattern["evidence"]["pattern_code"] = "NOT allowed";
    const auto invalidPatternResult = pauseable::validateBehaviorInference(
        "pauseable/ai/repetitive/decision", invalidPattern.dump(), config, now);
    assert(invalidPatternResult.disposition == pauseable::ValidationDisposition::InvalidSchema);

    auto oversizedScore = repetitive;
    oversizedScore["risk_score"] = std::numeric_limits<unsigned long long>::max();
    const auto oversizedScoreResult = pauseable::validateBehaviorInference(
        "pauseable/ai/repetitive/decision", oversizedScore.dump(), config, now);
    assert(oversizedScoreResult.disposition == pauseable::ValidationDisposition::InvalidSchema);

    const auto ledgerPath = std::filesystem::temp_directory_path() /
        "pauseable-behavior-inference-test.jsonl";
    std::error_code ignored;
    std::filesystem::remove(ledgerPath, ignored);
    const auto ledgerNow = std::chrono::system_clock::now();
    {
        pauseable::EventLedger ledger(ledgerPath.string(), 10000, std::chrono::hours(24));
        assert(ledger.inspect("evt-ledger-1", repetitive.dump(), ledgerNow) ==
               pauseable::EventLedger::Result::NewEvent);
        assert(ledger.size() == 0);
        assert(ledger.record("evt-ledger-1", repetitive.dump(), ledgerNow) ==
               pauseable::EventLedger::Result::NewEvent);
        assert(ledger.record("evt-ledger-1", repetitive.dump(), ledgerNow) ==
               pauseable::EventLedger::Result::Duplicate);
        assert(ledger.record("evt-ledger-1", wandering.dump(), ledgerNow) ==
               pauseable::EventLedger::Result::Conflict);
    }
    {
        pauseable::EventLedger ledger(ledgerPath.string(), 10000, std::chrono::hours(24));
        assert(ledger.size() == 1);
        assert(ledger.record("evt-ledger-1", repetitive.dump(), ledgerNow) ==
               pauseable::EventLedger::Result::Duplicate);
    }
    std::filesystem::remove(ledgerPath, ignored);

    {
        pauseable::EventLedger ledger(ledgerPath.string(), 10000, std::chrono::hours(24));
        assert(ledger.record("evt-expired", repetitive.dump(), ledgerNow - std::chrono::hours(25)) ==
               pauseable::EventLedger::Result::NewEvent);
    }
    {
        pauseable::EventLedger ledger(ledgerPath.string(), 10000, std::chrono::hours(24));
        assert(ledger.size() == 0);
    }
    std::filesystem::remove(ledgerPath, ignored);

    std::cout << "behavior_inference_test: all checks passed\n";
    return 0;
}
