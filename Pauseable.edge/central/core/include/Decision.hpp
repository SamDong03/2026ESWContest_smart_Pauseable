#pragma once


#include <optional>
#include <string>

namespace pauseable {

enum class DecisionType {
    Normal,
    RepetitiveBehavior,
    WanderingSuspected,
    Unknown
};

enum class RiskLevel {
    Normal,
    Caution,
    Danger,
    Unknown
};

struct Decision {
    DecisionType type{DecisionType::Normal};
    RiskLevel risk{RiskLevel::Normal};
    std::string message;
    std::string eventId;
    std::string source;
    std::string occurredAt;
    std::optional<int> riskScore;
    std::string patternCode;
};

}
