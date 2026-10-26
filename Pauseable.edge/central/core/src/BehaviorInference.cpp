#include "BehaviorInference.hpp"

#include <algorithm>
#include <ctime>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

#include <nlohmann/json.hpp>

namespace pauseable {
namespace {

using Json = nlohmann::json;

const std::set<std::string> kRequiredFields = {
    "behavior", "contract_version", "device_id", "event_id",
    "inference_status", "occurred_at", "patient_id", "risk_level",
    "risk_score", "source"
};

const std::set<std::string> kAllowedFields = {
    "behavior", "contract_version", "device_id", "event_id", "evidence",
    "inference_status", "model_version", "occurred_at", "patient_id",
    "risk_level", "risk_score", "source"
};

const std::set<std::string> kAllowedEvidenceFields = {
    "decision_policy", "model_status", "observation_count", "pattern_code",
    "reason_codes", "reason_text", "window_seconds"
};

bool hasOnlyFields(const Json& value, const std::set<std::string>& allowed)
{
    for (auto item = value.cbegin(); item != value.cend(); ++item) {
        if (allowed.count(item.key()) == 0) return false;
    }
    return true;
}

bool hasRequiredFields(const Json& value)
{
    return std::all_of(kRequiredFields.begin(), kRequiredFields.end(), [&value](const auto& key) {
        return value.contains(key);
    });
}

bool validBoundedString(const Json& value, std::size_t minimum, std::size_t maximum)
{
    return value.is_string() && value.get_ref<const std::string&>().size() >= minimum &&
        value.get_ref<const std::string&>().size() <= maximum;
}

std::optional<unsigned long long> nonNegativeInteger(const Json& value)
{
    if (value.is_number_unsigned()) {
        return value.get<unsigned long long>();
    }
    if (value.is_number_integer()) {
        const auto signedValue = value.get<long long>();
        if (signedValue >= 0) return static_cast<unsigned long long>(signedValue);
    }
    return std::nullopt;
}

std::optional<std::chrono::system_clock::time_point> parseUtcTimestamp(const std::string& text)
{
    static const std::regex pattern(
        R"(^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]{1,9})?(Z|\+00:00)$)"
    );
    std::smatch match;
    if (!std::regex_match(text, match, pattern)) {
        return std::nullopt;
    }

    std::tm parsed{};
    parsed.tm_year = std::stoi(match[1].str()) - 1900;
    parsed.tm_mon = std::stoi(match[2].str()) - 1;
    parsed.tm_mday = std::stoi(match[3].str());
    parsed.tm_hour = std::stoi(match[4].str());
    parsed.tm_min = std::stoi(match[5].str());
    parsed.tm_sec = std::stoi(match[6].str());
    parsed.tm_isdst = 0;

#ifdef _WIN32
    const std::time_t seconds = _mkgmtime(&parsed);
#else
    const std::time_t seconds = timegm(&parsed);
#endif
    if (seconds == static_cast<std::time_t>(-1)) {
        return std::nullopt;
    }

    std::tm normalized{};
#ifdef _WIN32
    gmtime_s(&normalized, &seconds);
#else
    gmtime_r(&seconds, &normalized);
#endif
    if (normalized.tm_year != parsed.tm_year || normalized.tm_mon != parsed.tm_mon ||
        normalized.tm_mday != parsed.tm_mday || normalized.tm_hour != parsed.tm_hour ||
        normalized.tm_min != parsed.tm_min || normalized.tm_sec != parsed.tm_sec) {
        return std::nullopt;
    }

    auto result = std::chrono::system_clock::from_time_t(seconds);
    if (match[7].matched) {
        std::string fraction = match[7].str().substr(1);
        fraction.append(9 - fraction.size(), '0');
        result += std::chrono::nanoseconds(std::stoll(fraction));
    }
    return result;
}

std::optional<BehaviorSource> parseSource(const std::string& value)
{
    if (value == "repetitive-ai") {
        return BehaviorSource::RepetitiveAi;
    }
    if (value == "wandering-ai") {
        return BehaviorSource::WanderingAi;
    }
    return std::nullopt;
}

std::optional<BehaviorType> parseBehavior(const std::string& value)
{
    if (value == "normal") return BehaviorType::Normal;
    if (value == "repetitive") return BehaviorType::Repetitive;
    if (value == "wandering") return BehaviorType::Wandering;
    if (value == "unknown") return BehaviorType::Unknown;
    return std::nullopt;
}

std::optional<RiskLevel> parseRisk(const std::string& value)
{
    if (value == "normal") return RiskLevel::Normal;
    if (value == "caution") return RiskLevel::Caution;
    if (value == "danger") return RiskLevel::Danger;
    if (value == "unknown") return RiskLevel::Unknown;
    return std::nullopt;
}

std::optional<InferenceStatus> parseInferenceStatus(const std::string& value)
{
    if (value == "ok") return InferenceStatus::Ok;
    if (value == "insufficient_data") return InferenceStatus::InsufficientData;
    if (value == "sensor_error") return InferenceStatus::SensorError;
    if (value == "model_error") return InferenceStatus::ModelError;
    return std::nullopt;
}

BehaviorValidationResult rejected(ValidationDisposition disposition, std::string detail)
{
    return {disposition, std::nullopt, std::move(detail)};
}

struct LedgerEntry {
    std::string eventId;
    std::string canonicalPayload;
    std::int64_t recordedAt{};
};

}

BehaviorValidationResult validateBehaviorInference(
    const std::string& topic,
    const std::string& payload,
    const BehaviorValidationConfig& config,
    std::chrono::system_clock::time_point now)
{
    Json document;
    try {
        document = Json::parse(payload);
    } catch (const std::exception& error) {
        return rejected(ValidationDisposition::InvalidSchema, std::string("invalid_json: ") + error.what());
    }

    if (!document.is_object() || !hasRequiredFields(document) ||
        !hasOnlyFields(document, kAllowedFields)) {
        return rejected(ValidationDisposition::InvalidSchema, "top_level_fields");
    }

    const auto stringField = [&document](const char* name) -> std::optional<std::string> {
        if (!document.at(name).is_string()) return std::nullopt;
        return document.at(name).get<std::string>();
    };

    const auto contractVersion = stringField("contract_version");
    const auto eventId = stringField("event_id");
    const auto occurredAt = stringField("occurred_at");
    const auto patientId = stringField("patient_id");
    const auto deviceId = stringField("device_id");
    const auto sourceText = stringField("source");
    const auto behaviorText = stringField("behavior");
    const auto riskText = stringField("risk_level");
    const auto statusText = stringField("inference_status");

    if (!contractVersion || !eventId || !occurredAt || !patientId || !deviceId ||
        !sourceText || !behaviorText || !riskText || !statusText) {
        return rejected(ValidationDisposition::InvalidSchema, "required_field_type");
    }
    if (*contractVersion != "1.0") {
        return rejected(ValidationDisposition::InvalidSchema, "unsupported_contract_version");
    }
    static const std::regex idPattern(R"(^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$)");
    if (!std::regex_match(*eventId, idPattern)) {
        return rejected(ValidationDisposition::InvalidSchema, "event_id");
    }
    if (*patientId != config.patientId || *deviceId != config.deviceId) {
        return rejected(ValidationDisposition::InvalidSchema, "deployment_identity");
    }

    const auto source = parseSource(*sourceText);
    const auto behavior = parseBehavior(*behaviorText);
    const auto risk = parseRisk(*riskText);
    const auto status = parseInferenceStatus(*statusText);
    if (!source || !behavior || !risk || !status) {
        return rejected(ValidationDisposition::InvalidSchema, "enum_value");
    }

    const std::string expectedTopic = *source == BehaviorSource::RepetitiveAi
        ? "pauseable/ai/repetitive/decision"
        : "pauseable/ai/wandering/decision";
    if (topic != expectedTopic) {
        return rejected(ValidationDisposition::TopicMismatch, "topic_source_mismatch");
    }
    if ((*source == BehaviorSource::RepetitiveAi && *behavior == BehaviorType::Wandering) ||
        (*source == BehaviorSource::WanderingAi && *behavior == BehaviorType::Repetitive)) {
        return rejected(ValidationDisposition::InvalidSchema, "source_behavior_mismatch");
    }

    std::optional<int> riskScore;
    if (const auto value = nonNegativeInteger(document.at("risk_score"))) {
        if (*value > 100) {
            return rejected(ValidationDisposition::InvalidSchema, "risk_score_range");
        }
        riskScore = static_cast<int>(*value);
    } else if (!document.at("risk_score").is_null()) {
        return rejected(ValidationDisposition::InvalidSchema, "risk_score_type");
    }

    if (*status == InferenceStatus::Ok) {
        if (*behavior == BehaviorType::Unknown || *risk == RiskLevel::Unknown || !riskScore) {
            return rejected(ValidationDisposition::InvalidSchema, "ok_semantics");
        }
        if ((*behavior == BehaviorType::Normal) != (*risk == RiskLevel::Normal)) {
            return rejected(ValidationDisposition::InvalidSchema, "behavior_risk_mismatch");
        }
    } else if (*behavior != BehaviorType::Unknown || *risk != RiskLevel::Unknown || riskScore) {
        return rejected(ValidationDisposition::InvalidSchema, "non_ok_semantics");
    }

    std::string modelVersion;
    if (document.contains("model_version")) {
        if (!validBoundedString(document.at("model_version"), 1, 64)) {
            return rejected(ValidationDisposition::InvalidSchema, "model_version");
        }
        modelVersion = document.at("model_version").get<std::string>();
    }

    std::string reasonText;
    std::string modelStatus;
    std::string patternCodeValue;
    if (document.contains("evidence")) {
        const auto& evidence = document.at("evidence");
        if (!evidence.is_object() || !hasOnlyFields(evidence, kAllowedEvidenceFields)) {
            return rejected(ValidationDisposition::InvalidSchema, "evidence_fields");
        }
        if (evidence.contains("reason_text")) {
            if (!validBoundedString(evidence.at("reason_text"), 0, 500)) {
                return rejected(ValidationDisposition::InvalidSchema, "evidence_reason_text");
            }
            reasonText = evidence.at("reason_text").get<std::string>();
        }
        if (evidence.contains("model_status")) {
            if (!validBoundedString(evidence.at("model_status"), 0, 64)) {
                return rejected(ValidationDisposition::InvalidSchema, "evidence_model_status");
            }
            modelStatus = evidence.at("model_status").get<std::string>();
        }
        if (evidence.contains("pattern_code")) {
            static const std::regex patternCode(R"(^[a-z0-9_]{1,64}$)");
            if (!evidence.at("pattern_code").is_string() ||
                !std::regex_match(evidence.at("pattern_code").get<std::string>(), patternCode)) {
                return rejected(ValidationDisposition::InvalidSchema, "evidence_pattern_code");
            }
            patternCodeValue = evidence.at("pattern_code").get<std::string>();
        }
        if (evidence.contains("decision_policy") &&
            !validBoundedString(evidence.at("decision_policy"), 0, 64)) {
            return rejected(ValidationDisposition::InvalidSchema, "evidence_decision_policy");
        }
        if (evidence.contains("window_seconds")) {
            const auto value = nonNegativeInteger(evidence.at("window_seconds"));
            if (!value || *value < 1) {
                return rejected(ValidationDisposition::InvalidSchema, "evidence_window_seconds");
            }
        }
        if (evidence.contains("observation_count") &&
            !nonNegativeInteger(evidence.at("observation_count"))) {
            return rejected(ValidationDisposition::InvalidSchema, "evidence_observation_count");
        }
        if (evidence.contains("reason_codes")) {
            const auto& values = evidence.at("reason_codes");
            if (!values.is_array() || values.size() > 20) {
                return rejected(ValidationDisposition::InvalidSchema, "evidence_reason_codes");
            }
            std::set<std::string> unique;
            static const std::regex codePattern(R"(^[a-z0-9_]{1,64}$)");
            for (const auto& value : values) {
                if (!value.is_string() || !std::regex_match(value.get<std::string>(), codePattern) ||
                    !unique.insert(value.get<std::string>()).second) {
                    return rejected(ValidationDisposition::InvalidSchema, "evidence_reason_codes");
                }
            }
        }
    }

    const auto timestamp = parseUtcTimestamp(*occurredAt);
    if (!timestamp) {
        return rejected(ValidationDisposition::InvalidSchema, "occurred_at");
    }
    if (now - *timestamp > config.staleAfter) {
        return rejected(ValidationDisposition::StaleEvent, "older_than_stale_limit");
    }
    if (*timestamp - now > config.maximumFutureSkew) {
        return rejected(ValidationDisposition::FutureEvent, "beyond_future_clock_skew");
    }

    BehaviorInference inference;
    inference.contractVersion = *contractVersion;
    inference.eventId = *eventId;
    inference.occurredAt = *occurredAt;
    inference.occurredAtTime = *timestamp;
    inference.patientId = *patientId;
    inference.deviceId = *deviceId;
    inference.source = *source;
    inference.behavior = *behavior;
    inference.risk = *risk;
    inference.riskScore = riskScore;
    inference.inferenceStatus = *status;
    inference.modelVersion = std::move(modelVersion);
    inference.patternCode = std::move(patternCodeValue);
    inference.reasonText = std::move(reasonText);
    inference.modelStatus = std::move(modelStatus);
    inference.canonicalPayload = document.dump();
    return {ValidationDisposition::Accepted, std::move(inference), "accepted"};
}

Decision toDecision(const BehaviorInference& inference)
{
    Decision decision;
    decision.eventId = inference.eventId;
    decision.source = toString(inference.source);
    decision.occurredAt = inference.occurredAt;
    decision.risk = inference.risk;
    decision.riskScore = inference.riskScore;
    decision.patternCode = inference.patternCode;

    switch (inference.behavior) {
    case BehaviorType::Normal:
        decision.type = DecisionType::Normal;
        decision.message = "정상 상태로 확인되었습니다.";
        break;
    case BehaviorType::Repetitive:
        decision.type = DecisionType::RepetitiveBehavior;
        decision.message = "반복 행동이 감지되었습니다. 안전을 확인해주세요.";
        break;
    case BehaviorType::Wandering:
        decision.type = DecisionType::WanderingSuspected;
        decision.message = "배회 의심 행동이 감지되었습니다. 안전을 확인해주세요.";
        break;
    case BehaviorType::Unknown:
        decision.type = DecisionType::Unknown;
        decision.message = "판단에 필요한 관측이 부족합니다.";
        break;
    }
    return decision;
}

std::string toString(BehaviorSource value)
{
    return value == BehaviorSource::RepetitiveAi ? "repetitive-ai" : "wandering-ai";
}

std::string toString(BehaviorType value)
{
    switch (value) {
    case BehaviorType::Normal: return "normal";
    case BehaviorType::Repetitive: return "repetitive";
    case BehaviorType::Wandering: return "wandering";
    case BehaviorType::Unknown: return "unknown";
    }
    return "unknown";
}

std::string toString(InferenceStatus value)
{
    switch (value) {
    case InferenceStatus::Ok: return "ok";
    case InferenceStatus::InsufficientData: return "insufficient_data";
    case InferenceStatus::SensorError: return "sensor_error";
    case InferenceStatus::ModelError: return "model_error";
    }
    return "model_error";
}

std::string toString(RiskLevel value)
{
    switch (value) {
    case RiskLevel::Normal: return "normal";
    case RiskLevel::Caution: return "caution";
    case RiskLevel::Danger: return "danger";
    case RiskLevel::Unknown: return "unknown";
    }
    return "unknown";
}

std::string toString(DecisionType value)
{
    switch (value) {
    case DecisionType::Normal: return "normal";
    case DecisionType::RepetitiveBehavior: return "repetitive_behavior";
    case DecisionType::WanderingSuspected: return "wandering_suspected";
    case DecisionType::Unknown: return "unknown";
    }
    return "unknown";
}

struct EventLedger::Impl {
    std::string filePath;
    std::size_t maximumEntries;
    std::chrono::hours retention;
    mutable std::mutex mutex;
    std::deque<LedgerEntry> entries;
    std::unordered_map<std::string, std::pair<std::string, std::int64_t>> index;

    Impl(std::string pathValue, std::size_t maximum, std::chrono::hours keep)
        : filePath(std::move(pathValue)), maximumEntries(maximum), retention(keep)
    {
        if (filePath.empty() || maximumEntries == 0 || retention.count() <= 0) {
            throw std::invalid_argument("EventLedger configuration is invalid");
        }
        load();
    }

    void load()
    {
        std::ifstream input(filePath);
        std::string line;
        while (std::getline(input, line)) {
            try {
                const auto row = Json::parse(line);
                LedgerEntry entry{
                    row.at("event_id").get<std::string>(),
                    row.at("canonical_payload").get<std::string>(),
                    row.at("recorded_at_epoch").get<std::int64_t>()
                };
                index[entry.eventId] = {entry.canonicalPayload, entry.recordedAt};
                entries.push_back(std::move(entry));
            } catch (const std::exception&) {

            }
        }
        prune(std::chrono::system_clock::now());
    }

    void prune(std::chrono::system_clock::time_point now)
    {
        const auto minimumTime = std::chrono::duration_cast<std::chrono::seconds>(
            (now - retention).time_since_epoch()).count();
        while (!entries.empty() &&
               (entries.front().recordedAt < minimumTime || entries.size() > maximumEntries)) {
            const auto current = index.find(entries.front().eventId);
            if (current != index.end() && current->second.second == entries.front().recordedAt) {
                index.erase(current);
            }
            entries.pop_front();
        }
    }

    void persist()
    {
        const std::filesystem::path target(filePath);
        if (!target.parent_path().empty()) {
            std::filesystem::create_directories(target.parent_path());
        }
        const auto temporary = target.string() + ".tmp";
        std::ofstream output(temporary, std::ios::trunc);
        if (!output.is_open()) {
            throw std::runtime_error("Could not write event ledger temporary file");
        }
        for (const auto& entry : entries) {
            output << Json{
                {"event_id", entry.eventId},
                {"canonical_payload", entry.canonicalPayload},
                {"recorded_at_epoch", entry.recordedAt}
            }.dump() << '\n';
        }
        output.flush();
        if (!output.good()) {
            throw std::runtime_error("Could not flush event ledger");
        }
        output.close();

        std::error_code error;
        std::filesystem::rename(temporary, target, error);
        if (error) {
            std::filesystem::remove(target, error);
            error.clear();
            std::filesystem::rename(temporary, target, error);
        }
        if (error) {
            throw std::runtime_error("Could not replace event ledger: " + error.message());
        }
    }
};

EventLedger::EventLedger(std::string path, std::size_t maximumEntries, std::chrono::hours retention)
    : impl_(std::make_shared<Impl>(std::move(path), maximumEntries, retention))
{
}

EventLedger::Result EventLedger::inspect(
    const std::string& eventId,
    const std::string& canonicalPayload,
    std::chrono::system_clock::time_point now)
{
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->prune(now);
    const auto existing = impl_->index.find(eventId);
    if (existing == impl_->index.end()) return Result::NewEvent;
    return existing->second.first == canonicalPayload ? Result::Duplicate : Result::Conflict;
}

EventLedger::Result EventLedger::record(
    const std::string& eventId,
    const std::string& canonicalPayload,
    std::chrono::system_clock::time_point now)
{
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->prune(now);
    const auto existing = impl_->index.find(eventId);
    if (existing != impl_->index.end()) {
        return existing->second.first == canonicalPayload ? Result::Duplicate : Result::Conflict;
    }

    const auto recordedAt = std::chrono::duration_cast<std::chrono::seconds>(
        now.time_since_epoch()).count();
    impl_->entries.push_back({eventId, canonicalPayload, recordedAt});
    impl_->index[eventId] = {canonicalPayload, recordedAt};
    impl_->prune(now);
    impl_->persist();
    return Result::NewEvent;
}

std::size_t EventLedger::size() const
{
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->entries.size();
}

const std::string& EventLedger::path() const
{
    return impl_->filePath;
}

}
