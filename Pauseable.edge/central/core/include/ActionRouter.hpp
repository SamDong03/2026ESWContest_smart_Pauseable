#pragma once

#include <chrono>
#include <cstddef>
#include <memory>
#include <string>

#include "Decision.hpp"

namespace pauseable {

enum class ActionDisposition {
    AuditOnly,
    Execute,
    Suppressed,
    Blocked
};

struct ActionPlan {
    ActionDisposition disposition{ActionDisposition::AuditOnly};
    std::string reason;
    Decision decision;
    bool notifyGuardian{false};
    bool speakLocal{false};
    bool controlAppliance{false};
};

struct ActionRouterConfig {
    bool repetitiveActionsEnabled{false};
    bool wanderingActionsEnabled{false};
    bool recoveryNotificationsEnabled{false};
    std::chrono::seconds repetitiveCooldown{900};
    std::chrono::seconds wanderingCooldown{300};
    std::string statePath;
};

class ActionRouter {
public:
    explicit ActionRouter(ActionRouterConfig config);

    ActionPlan route(
        const Decision& decision,
        std::chrono::system_clock::time_point now = std::chrono::system_clock::now());

    std::size_t stateCount() const;
    const std::string& statePath() const;

private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
};

std::string toString(ActionDisposition value);

}
