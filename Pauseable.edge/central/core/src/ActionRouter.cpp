#include "ActionRouter.hpp"

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <stdexcept>
#include <utility>

#include <nlohmann/json.hpp>

#include "BehaviorInference.hpp"

namespace pauseable {
namespace {

using Json = nlohmann::json;

struct SourceState {
    bool active{false};
    RiskLevel lastRisk{RiskLevel::Normal};
    std::int64_t lastNotifiedAt{0};
    std::string lastEventId;
};

int riskRank(RiskLevel value)
{
    switch (value) {
    case RiskLevel::Normal: return 0;
    case RiskLevel::Caution: return 1;
    case RiskLevel::Danger: return 2;
    case RiskLevel::Unknown: return -1;
    }
    return -1;
}

std::optional<RiskLevel> riskFromString(const std::string& value)
{
    if (value == "normal") return RiskLevel::Normal;
    if (value == "caution") return RiskLevel::Caution;
    if (value == "danger") return RiskLevel::Danger;
    if (value == "unknown") return RiskLevel::Unknown;
    return std::nullopt;
}

std::int64_t epochSeconds(std::chrono::system_clock::time_point value)
{
    return std::chrono::duration_cast<std::chrono::seconds>(value.time_since_epoch()).count();
}

bool sourceMatchesDecision(const Decision& decision)
{
    if (decision.type == DecisionType::RepetitiveBehavior) {
        return decision.source == "repetitive-ai";
    }
    if (decision.type == DecisionType::WanderingSuspected) {
        return decision.source == "wandering-ai";
    }
    return decision.source == "repetitive-ai" || decision.source == "wandering-ai";
}

}

struct ActionRouter::Impl {
    explicit Impl(ActionRouterConfig value) : config(std::move(value))
    {
        if (config.repetitiveCooldown.count() <= 0 ||
            config.wanderingCooldown.count() <= 0) {
            throw std::invalid_argument("Action cooldowns must be positive");
        }
        load();
    }

    ActionRouterConfig config;
    mutable std::mutex mutex;
    std::map<std::string, SourceState> states;

    void load()
    {
        if (config.statePath.empty()) return;
        std::ifstream input(config.statePath);
        if (!input.is_open()) return;

        Json document;
        input >> document;
        if (!document.is_object() || document.value("state_version", 0) != 1 ||
            !document.contains("sources") || !document.at("sources").is_object()) {
            throw std::runtime_error("Action Router state file has an unsupported format");
        }

        for (auto entry = document.at("sources").cbegin();
             entry != document.at("sources").cend(); ++entry) {
            if (entry.key() != "repetitive-ai" && entry.key() != "wandering-ai") {
                continue;
            }
            const auto& value = entry.value();
            if (!value.is_object() || !value.contains("active") ||
                !value.at("active").is_boolean() || !value.contains("last_risk") ||
                !value.at("last_risk").is_string() ||
                !value.contains("last_notified_at") ||
                !value.at("last_notified_at").is_number_integer() ||
                !value.contains("last_event_id") ||
                !value.at("last_event_id").is_string()) {
                throw std::runtime_error("Action Router source state is invalid");
            }
            const auto risk = riskFromString(value.at("last_risk").get<std::string>());
            if (!risk) throw std::runtime_error("Action Router risk state is invalid");
            states[entry.key()] = {
                value.at("active").get<bool>(),
                *risk,
                value.at("last_notified_at").get<std::int64_t>(),
                value.at("last_event_id").get<std::string>()};
        }
    }

    void persistLocked() const
    {
        if (config.statePath.empty()) return;

        Json sources = Json::object();
        for (const auto& entry : states) {
            sources[entry.first] = {
                {"active", entry.second.active},
                {"last_risk", toString(entry.second.lastRisk)},
                {"last_notified_at", entry.second.lastNotifiedAt},
                {"last_event_id", entry.second.lastEventId}};
        }
        const Json document{{"state_version", 1}, {"sources", std::move(sources)}};

        const std::filesystem::path path(config.statePath);
        if (!path.parent_path().empty()) {
            std::filesystem::create_directories(path.parent_path());
        }
        const std::filesystem::path temporary = path.string() + ".tmp";
        {
            std::ofstream output(temporary, std::ios::trunc);
            if (!output.is_open()) {
                throw std::runtime_error("Could not open Action Router state temporary file");
            }
            output << document.dump() << '\n';
            output.flush();
            if (!output.good()) {
                throw std::runtime_error("Could not write Action Router state");
            }
        }
        std::error_code error;
        std::filesystem::rename(temporary, path, error);
        if (error) {
            std::filesystem::remove(path, error);
            error.clear();
            std::filesystem::rename(temporary, path, error);
        }
        if (error) {
            throw std::runtime_error("Could not replace Action Router state: " + error.message());
        }
    }

    ActionPlan route(const Decision& decision, std::chrono::system_clock::time_point now)
    {
        ActionPlan plan;
        plan.decision = decision;

        if (!sourceMatchesDecision(decision)) {
            plan.disposition = ActionDisposition::Blocked;
            plan.reason = "source_decision_mismatch";
            return plan;
        }

        const bool sourceEnabled = decision.source == "repetitive-ai"
            ? config.repetitiveActionsEnabled
            : config.wanderingActionsEnabled;
        if (!sourceEnabled) {
            plan.disposition = ActionDisposition::Blocked;
            plan.reason = "source_actions_disabled";
            return plan;
        }

        std::lock_guard<std::mutex> lock(mutex);
        auto& state = states[decision.source];

        if (decision.type == DecisionType::Unknown || decision.risk == RiskLevel::Unknown) {
            plan.disposition = ActionDisposition::AuditOnly;
            plan.reason = "inference_unknown";
            return plan;
        }

        if (decision.type == DecisionType::Normal) {
            const bool recovered = state.active;
            state.active = false;
            state.lastRisk = RiskLevel::Normal;
            state.lastEventId = decision.eventId;
            persistLocked();

            if (recovered && config.recoveryNotificationsEnabled) {
                plan.disposition = ActionDisposition::Execute;
                plan.reason = "normal_recovery";
                plan.notifyGuardian = true;
            } else {
                plan.disposition = ActionDisposition::AuditOnly;
                plan.reason = recovered ? "normal_recovery_recorded" : "normal_observation";
            }
            return plan;
        }

        if (decision.risk != RiskLevel::Caution && decision.risk != RiskLevel::Danger) {
            plan.disposition = ActionDisposition::Blocked;
            plan.reason = "non_actionable_risk";
            return plan;
        }

        const auto cooldown = decision.source == "repetitive-ai"
            ? config.repetitiveCooldown
            : config.wanderingCooldown;
        const auto nowSeconds = epochSeconds(now);
        const bool firstRisk = !state.active;
        const bool sameEventRetry = state.active && state.lastEventId == decision.eventId;
        const bool escalated = state.active && riskRank(decision.risk) > riskRank(state.lastRisk);
        const bool cooldownElapsed = state.lastNotifiedAt == 0 ||
            nowSeconds - state.lastNotifiedAt >= cooldown.count();

        state.active = true;
        state.lastRisk = decision.risk;
        state.lastEventId = decision.eventId;

        if (firstRisk || sameEventRetry || escalated || cooldownElapsed) {
            state.lastNotifiedAt = nowSeconds;
            persistLocked();
            plan.disposition = ActionDisposition::Execute;
            plan.reason = firstRisk ? "first_risk_event"
                : sameEventRetry ? "same_event_retry"
                : escalated ? "risk_escalated" : "cooldown_elapsed";
            plan.notifyGuardian = true;
            plan.speakLocal = !sameEventRetry;
            return plan;
        }

        persistLocked();
        plan.disposition = ActionDisposition::Suppressed;
        plan.reason = "cooldown_active";
        return plan;
    }
};

ActionRouter::ActionRouter(ActionRouterConfig config)
    : impl_(std::make_shared<Impl>(std::move(config)))
{
}

ActionPlan ActionRouter::route(
    const Decision& decision,
    std::chrono::system_clock::time_point now)
{
    return impl_->route(decision, now);
}

std::size_t ActionRouter::stateCount() const
{
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->states.size();
}

const std::string& ActionRouter::statePath() const
{
    return impl_->config.statePath;
}

std::string toString(ActionDisposition value)
{
    switch (value) {
    case ActionDisposition::AuditOnly: return "audit_only";
    case ActionDisposition::Execute: return "execute";
    case ActionDisposition::Suppressed: return "suppressed";
    case ActionDisposition::Blocked: return "blocked";
    }
    return "blocked";
}

}
