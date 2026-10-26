#pragma once

#include <chrono>
#include <cstddef>
#include <memory>
#include <optional>
#include <string>

#include "Decision.hpp"

namespace pauseable {

enum class BehaviorSource {
    RepetitiveAi,
    WanderingAi
};

enum class BehaviorType {
    Normal,
    Repetitive,
    Wandering,
    Unknown
};

enum class InferenceStatus {
    Ok,
    InsufficientData,
    SensorError,
    ModelError
};

struct BehaviorInference {
    std::string contractVersion;
    std::string eventId;
    std::string occurredAt;
    std::chrono::system_clock::time_point occurredAtTime;
    std::string patientId;
    std::string deviceId;
    BehaviorSource source{BehaviorSource::RepetitiveAi};
    BehaviorType behavior{BehaviorType::Unknown};
    RiskLevel risk{RiskLevel::Unknown};
    std::optional<int> riskScore;
    InferenceStatus inferenceStatus{InferenceStatus::ModelError};
    std::string modelVersion;
    std::string patternCode;
    std::string reasonText;
    std::string modelStatus;
    std::string canonicalPayload;
};

struct BehaviorValidationConfig {
    std::string patientId{"byunwoojin"};
    std::string deviceId{"pi5-home-01"};
    std::chrono::seconds staleAfter{300};
    std::chrono::seconds maximumFutureSkew{30};
};

enum class ValidationDisposition {
    Accepted,
    InvalidSchema,
    TopicMismatch,
    StaleEvent,
    FutureEvent
};

struct BehaviorValidationResult {
    ValidationDisposition disposition{ValidationDisposition::InvalidSchema};
    std::optional<BehaviorInference> inference;
    std::string detail;
};

BehaviorValidationResult validateBehaviorInference(
    const std::string& topic,
    const std::string& payload,
    const BehaviorValidationConfig& config,
    std::chrono::system_clock::time_point now = std::chrono::system_clock::now());

Decision toDecision(const BehaviorInference& inference);
std::string toString(BehaviorSource value);
std::string toString(BehaviorType value);
std::string toString(InferenceStatus value);
std::string toString(RiskLevel value);
std::string toString(DecisionType value);

class EventLedger {
public:
    enum class Result {
        NewEvent,
        Duplicate,
        Conflict
    };

    explicit EventLedger(
        std::string path,
        std::size_t maximumEntries = 10000,
        std::chrono::hours retention = std::chrono::hours(24));

    Result inspect(
        const std::string& eventId,
        const std::string& canonicalPayload,
        std::chrono::system_clock::time_point now = std::chrono::system_clock::now());

    Result record(
        const std::string& eventId,
        const std::string& canonicalPayload,
        std::chrono::system_clock::time_point now = std::chrono::system_clock::now());

    std::size_t size() const;
    const std::string& path() const;

private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
};

}
