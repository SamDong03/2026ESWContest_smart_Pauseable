
#include <algorithm>
#include <cerrno>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <alog.hpp>
#include <amclient/AMClient.h>
#include <nlohmann/json.hpp>
#include <sdbus-c++/sdbus-c++.h>
#include <fcntl.h>
#include <pthread.h>
#include <sys/stat.h>
#include <unistd.h>


#define USE_SD_EVENT

#ifdef USE_SD_EVENT
#include <systemd/sd-event.h>
#endif

#include "ActionRouter.hpp"
#include "BehaviorInference.hpp"
#include "DecisionEvent.hpp"
#include "DecisionGatewayClient.hpp"
#include "DecisionOutbox.hpp"
#include "EmbeddedHaConfig.hpp"
#include "GatewayClient.hpp"
#include "HAEntityClient.hpp"
#include "MmWaveArchive.hpp"
#include "MmWaveReceiver.hpp"
#include "MqttDecisionSubscriber.hpp"
#include "PiperTtsEngine.hpp"
#include "PropertyManagerClient.hpp"

namespace {
bool requestYoutubePlayback()
{
    const int fd = open(
        "/run/pauseable-youtube-request.fifo",
        O_WRONLY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW
    );

    if (fd < 0) {
        return false;
    }

    struct stat information {};
    if (fstat(fd, &information) != 0 ||
        !S_ISFIFO(information.st_mode) ||
        information.st_uid != geteuid()) {
        close(fd);
        return false;
    }

    sigset_t blockedSignals;
    sigset_t previousSignals;
    sigset_t pendingSignals;

    sigemptyset(&blockedSignals);
    sigaddset(&blockedSignals, SIGPIPE);

    if (pthread_sigmask(
            SIG_BLOCK,
            &blockedSignals,
            &previousSignals
        ) != 0) {
        close(fd);
        return false;
    }

    if (sigpending(&pendingSignals) != 0) {
        pthread_sigmask(SIG_SETMASK, &previousSignals, nullptr);
        close(fd);
        return false;
    }

    const bool alreadyPending =
        sigismember(&pendingSignals, SIGPIPE) == 1;

    constexpr char request[] = "PLAY_TROT\n";
    ssize_t written;

    do {
        written = write(fd, request, sizeof(request) - 1);
    } while (written < 0 && errno == EINTR);

    const int writeError = written < 0 ? errno : 0;

    if (writeError == EPIPE && !alreadyPending) {
        const timespec timeout {};
        while (sigtimedwait(
                   &blockedSignals,
                   nullptr,
                   &timeout
               ) < 0 && errno == EINTR) {
        }
    }

    close(fd);
    pthread_sigmask(SIG_SETMASK, &previousSignals, nullptr);

    return written == static_cast<ssize_t>(sizeof(request) - 1);
}

struct HaRuntimeConfig
{
    std::string websocketUrl;
    std::vector<std::string> entityIds;
};

HaRuntimeConfig loadHaRuntimeConfig(const std::string& path)
{
    std::ifstream input(path);
    nlohmann::json document;
    if (input.is_open()) {
        input >> document;
    } else {
        document = nlohmann::json::parse(std::string(pauseable::kEmbeddedHaConfig));
    }

    HaRuntimeConfig config;
    config.websocketUrl = document.at("websocket_url").get<std::string>();

    const auto entities = document.find("entities");
    if (entities != document.end()) {
        if (!entities->is_array()) {
            throw std::runtime_error("Home Assistant config 'entities' must be an array");
        }

        for (const auto& entity : *entities) {
            if (!entity.is_string()) {
                throw std::runtime_error("Every Home Assistant entity ID must be a string");
            }
            config.entityIds.push_back(entity.get<std::string>());
        }
    }

    return config;
}

std::string environmentOrDefault(const char* name, const std::string& fallback)
{
    const char* value = std::getenv(name);
    return value == nullptr || std::string(value).empty() ? fallback : value;
}

std::string resolveRuntimeEnvironmentPath()
{
    const char* configuredPath = std::getenv("PAUSEABLE_ENV_PATH");
    if (configuredPath != nullptr && std::string(configuredPath).empty() == false) {
        return configuredPath;
    }

    const char* home = std::getenv("HOME");
    if (home != nullptr && std::string(home).empty() == false) {
        const std::string appHomePath = std::string(home) + "/ha.env";
        std::ifstream appHomeFile(appHomePath);
        if (appHomeFile.is_open()) {
            return appHomePath;
        }
    }

    return "/var/lib/pauseable/ha.env";
}

double environmentDoubleOrDefault(const char* name, double fallback)
{
    const char* value = std::getenv(name);
    if (value == nullptr || std::string(value).empty()) {
        return fallback;
    }

    std::size_t parsedLength = 0;
    const double parsed = std::stod(value, &parsedLength);
    if (parsedLength != std::strlen(value)) {
        throw std::invalid_argument(std::string(name) + " is not a valid number");
    }
    return parsed;
}

bool environmentFlagOrDefault(const char* name, bool fallback)
{
    const char* value = std::getenv(name);
    if (value == nullptr || std::string(value).empty()) {
        return fallback;
    }
    if (std::string(value) == "1") return true;
    if (std::string(value) == "0") return false;
    throw std::invalid_argument(std::string(name) + " must be 0 or 1");
}

unsigned long environmentUnsignedOrDefault(
    const char* name,
    unsigned long fallback,
    unsigned long maximum)
{
    const std::string text = environmentOrDefault(name, std::to_string(fallback));
    if (text.empty() || text.find_first_not_of("0123456789") != std::string::npos) {
        throw std::invalid_argument(std::string(name) + " must be an unsigned integer");
    }
    const auto parsed = std::stoul(text);
    if (parsed == 0 || parsed > maximum) {
        throw std::invalid_argument(std::string(name) + " is outside allowed range");
    }
    return parsed;
}

std::string defaultEventLedgerPath()
{
    const char* home = std::getenv("HOME");
    if (home != nullptr && std::string(home).empty() == false) {
        return std::string(home) + "/decision-events.jsonl";
    }
    return "/tmp/pauseable-decision-events.jsonl";
}

std::string defaultRuntimeDataPath(const std::string& name)
{
    const char* home = std::getenv("HOME");
    if (home != nullptr && std::string(home).empty() == false) {
        return std::string(home) + "/" + name;
    }
    return "/tmp/pauseable-" + name;
}

std::size_t loadEnvironmentFile(const std::string& path)
{
    std::ifstream input(path);
    if (!input.is_open()) {
        return 0;
    }

    std::size_t loadedCount = 0;
    std::string line;
    while (std::getline(input, line)) {
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        if (line.empty() || line.front() == '#') {
            continue;
        }

        const std::size_t separator = line.find('=');
        if (separator == std::string::npos || separator == 0) {
            throw std::runtime_error("Invalid environment entry in " + path);
        }

        const std::string key = line.substr(0, separator);
        const bool validKey = std::all_of(key.begin(), key.end(), [](unsigned char value) {
            return std::isalnum(value) != 0 || value == '_';
        });
        if (!validKey) {
            throw std::runtime_error("Invalid environment variable name in " + path);
        }

        const std::string value = line.substr(separator + 1);
        if (setenv(key.c_str(), value.c_str(), 0) != 0) {
            throw std::runtime_error(
                "Could not load environment variable " + key + ": " + std::strerror(errno)
            );
        }
        ++loadedCount;
    }

    return loadedCount;
}

std::string ttsMessageFor(const pauseable::HaEntityEvent& event)
{
    if (event.entityId == "input_boolean.pauseable_washing_machine") {
        return event.state == "on"
            ? "세탁기 전원이 켜졌습니다."
            : "세탁기 전원이 꺼졌습니다.";
    }

    return event.state == "on"
        ? "기기가 켜졌습니다."
        : "기기 상태가 변경되었습니다.";
}

}

#define APP_ID "com.atlas.app.pauseableatlas"

volatile sig_atomic_t g_stop_requested = 0;

void signalHandler(int signal)
{
    (void)signal;
    g_stop_requested = 1;
}

int main()
{
    try {
        std::shared_ptr<sdbus::IConnection> connection =
            sdbus::createSystemBusConnection();


        AMClient client(APP_ID);

        client.registerRestartEventCallback([](const std::vector<std::string>& params) {
            try {
                alog::logInfo("EVT_RESTART", "Restart event callback executing with params:");
                for (std::size_t index = 0; index < params.size(); ++index) {
                    alog::logInfo("EVT_RESTART", "arg[{}]: {}", index, params[index]);
                }
            } catch (const std::exception& e) {
                alog::logError("EVT_RESTART", "Exception in restart callback: {}", e.what());
            }
        });

        client.registerPauseEventCallback([](const std::vector<std::string>& params) {
            try {
                alog::logInfo("EVT_PAUSE", "Pause event callback executing with params:");
                for (std::size_t index = 0; index < params.size(); ++index) {
                    alog::logInfo("EVT_PAUSE", "arg[{}]: {}", index, params[index]);
                }
            } catch (const std::exception& e) {
                alog::logError("EVT_PAUSE", "Exception in pause callback: {}", e.what());
            }
        });

        client.initializeCallbacks();
        alog::logInfo("APP_LAUNCHED", "The Central Atlas App launched successfully");

        const std::string runtimeEnvironmentPath = resolveRuntimeEnvironmentPath();
        try {
            const std::size_t loadedVariables = loadEnvironmentFile(runtimeEnvironmentPath);
            if (loadedVariables == 0) {
                alog::logWarn(
                    "ENV_FILE_MISSING",
                    "No Pauseable runtime environment was loaded from {}",
                    runtimeEnvironmentPath
                );
            } else {
                alog::logInfo(
                    "ENV_FILE_LOADED",
                    "Loaded {} Pauseable runtime variables from {}",
                    loadedVariables,
                    runtimeEnvironmentPath
                );
            }
        } catch (const std::exception& error) {
            alog::logError("ENV_FILE_FAILED", "Could not load Pauseable environment: {}", error.what());
        }


        std::unique_ptr<pauseable::MmWaveArchive> mmwaveArchive;
        std::unique_ptr<pauseable::MmWaveReceiver> mmwaveReceiver;

        const std::string mmwaveEnabled =
            environmentOrDefault("MMWAVE_ENABLED", "0");

        if (mmwaveEnabled == "1") {
            auto number = [](const char* name,
                             unsigned long fallback,
                             unsigned long maximum) {
                return environmentUnsignedOrDefault(name, fallback, maximum);
            };

            const std::string archiveEnabled =
                environmentOrDefault("MMWAVE_ARCHIVE_ENABLED", "0");

            if (archiveEnabled == "1") {
                try {
                    pauseable::MmWaveArchiveConfig archiveConfig;
                    archiveConfig.directory = environmentOrDefault(
                        "MMWAVE_ARCHIVE_DIR",
                        "/data/pauseable/mmwave");
                    archiveConfig.sampleEveryMs = number(
                        "MMWAVE_ARCHIVE_SAMPLE_MS",
                        5000,
                        3600000);
                    archiveConfig.maxTotalBytes =
                        static_cast<std::uint64_t>(number(
                            "MMWAVE_ARCHIVE_MAX_BYTES",
                            50331648,
                            1073741824));
                    archiveConfig.maxRetentionDays =
                        static_cast<std::uint32_t>(number(
                            "MMWAVE_ARCHIVE_MAX_DAYS",
                            7,
                            365));

                    mmwaveArchive =
                        std::make_unique<pauseable::MmWaveArchive>(
                            archiveConfig,
                            [](const nlohmann::json& report) {
                                const std::string kind =
                                    report.value("kind", "");

                                if (kind == "mmwave_archive_ready") {
                                    alog::logInfo(
                                        "MMWAVE_ARCHIVE_READY",
                                        "directory={} sample_ms={} max_bytes={} days={}",
                                        report.value("directory", ""),
                                        report.value(
                                            "sample_every_ms",
                                            0ULL),
                                        report.value(
                                            "max_total_bytes",
                                            0ULL),
                                        report.value(
                                            "max_retention_days",
                                            0U));
                                } else if (
                                    kind == "mmwave_archive_error") {
                                    alog::logError(
                                        "MMWAVE_ARCHIVE_FAILED",
                                        "{}",
                                        report.value(
                                            "message",
                                            "unknown error"));
                                }
                            });

                    mmwaveArchive->start();
                } catch (const std::exception& error) {
                    alog::logError(
                        "MMWAVE_ARCHIVE_START_FAILED",
                        "{}",
                        error.what());
                    mmwaveArchive.reset();
                }
            } else {
                alog::logInfo(
                    "MMWAVE_ARCHIVE_DISABLED",
                    "Set MMWAVE_ARCHIVE_ENABLED=1 to enable bounded private storage");
            }

            auto* archiveForReceiver = mmwaveArchive.get();

            try {
                pauseable::MmWaveReceiverConfig config;
                config.bindAddress =
                    environmentOrDefault(
                        "MMWAVE_BIND",
                        "127.0.0.1");
                config.port = static_cast<std::uint16_t>(
                    number("MMWAVE_PORT", 5005, 65535));
                config.staleAfterMs =
                    number("MMWAVE_STALE_MS", 3000, 3600000);
                config.summaryEveryMs =
                    number("MMWAVE_SUMMARY_MS", 5000, 60000);
                config.allowPeer =
                    environmentOrDefault("MMWAVE_ALLOW_PEER", "");

                mmwaveReceiver =
                    std::make_unique<pauseable::MmWaveReceiver>(
                        config,
                        [archiveForReceiver](
                            const nlohmann::json& report) {
                            if (archiveForReceiver != nullptr) {
                                archiveForReceiver->submit(report);
                            }

                            const std::string kind =
                                report.value("kind", "");

                            if (kind == "mmwave_ready") {
                                alog::logInfo(
                                    "MMWAVE_READY",
                                    "UDP {}:{} (observation only)",
                                    report.at("address").get<std::string>(),
                                    report.at("port").get<int>());
                            } else if (
                                kind == "mmwave_summary" ||
                                kind == "mmwave_stopped") {
                                alog::logInfo(
                                    "MMWAVE_SUMMARY",
                                    "transport={} counters={}",
                                    report.at("transport").dump(),
                                    report.at("counters").dump());

                                for (const auto& stream :
                                     report.at("streams")) {

                                    alog::logInfo(
                                        "MMWAVE_STATE",
                                        "sensor={} origin={} quality={} observation={}",
                                        stream.at("sensor_id")
                                            .get<std::string>(),
                                        stream.at("data_origin")
                                            .get<std::string>(),
                                        stream.at("quality")
                                            .get<std::string>(),
                                        stream.at("observation")
                                            .get<std::string>());
                                }
                            } else if (kind == "mmwave_error") {
                                alog::logError(
                                    "MMWAVE_FAILED",
                                    "{}",
                                    report.value(
                                        "detail",
                                        "receiver stopped"));
                            }
                        });

                mmwaveReceiver->start();
            } catch (const std::exception& error) {
                alog::logError(
                    "MMWAVE_START_FAILED",
                    "{}",
                    error.what());
                mmwaveReceiver.reset();
            }
        } else {
            alog::logInfo(
                "MMWAVE_DISABLED",
                "Set MMWAVE_ENABLED=1 to enable C-stage observation");
        }

        std::shared_ptr<pauseable::GatewayClient> gatewayClient;
        const std::string gatewayEventUrl = environmentOrDefault("GATEWAY_EVENT_URL", "");
        if (gatewayEventUrl.empty()) {
            alog::logWarn(
                "GATEWAY_DISABLED",
                "GATEWAY_EVENT_URL is not set; Flutter forwarding is disabled"
            );
        } else {
            try {
                pauseable::GatewayConfig gatewayConfig;
                gatewayConfig.eventUrl = gatewayEventUrl;
                gatewayConfig.bearerToken = environmentOrDefault(
                    "PAUSEABLE_DEVICE_TOKEN", "");
                gatewayConfig.patientId = environmentOrDefault(
                    "PAUSEABLE_PATIENT_ID", "byunwoojin");
                gatewayConfig.timeout = std::chrono::seconds(
                    environmentUnsignedOrDefault("GATEWAY_TIMEOUT_SECONDS", 8, 60));
                gatewayClient = std::make_shared<pauseable::GatewayClient>(
                    std::move(gatewayConfig));
                alog::logInfo(
                    "GATEWAY_READY",
                    "Authenticated Gateway forwarding is configured for patient_id={}",
                    environmentOrDefault("PAUSEABLE_PATIENT_ID", "byunwoojin"));
            } catch (const std::exception& error) {
                alog::logError(
                    "GATEWAY_DISABLED",
                    "Gateway configuration is invalid: {}",
                    error.what());
            }
        }

        std::shared_ptr<pauseable::PiperTtsEngine> ttsEngine;
        try {
            const std::string piperRoot = environmentOrDefault(
                "PIPER_ROOT",
                "/var/lib/pauseable/piper-guardian"
            );
            const std::string ttsOutputPath = environmentOrDefault(
                "TTS_OUTPUT_PATH",
                "/var/lib/pauseable/pauseable-tts.wav"
            );
            const double ttsGain = environmentDoubleOrDefault("TTS_GAIN", 2.0);
            ttsEngine = std::make_shared<pauseable::PiperTtsEngine>(
                piperRoot,
                ttsOutputPath,
                ttsGain
            );
            alog::logInfo("TTS_READY", "Local Piper TTS is configured with gain {}", ttsGain);
        } catch (const std::exception& error) {
            alog::logWarn("TTS_DISABLED", "Local Piper TTS is unavailable: {}", error.what());
        }

        std::shared_ptr<pauseable::ActionRouter> actionRouter;
        const bool repetitiveActionsEnabled =
            environmentFlagOrDefault("REPETITIVE_ACTIONS_ENABLED", false);
        const bool wanderingActionsEnabled =
            environmentFlagOrDefault("WANDERING_ACTIONS_ENABLED", false);
        const bool recoveryNotificationsEnabled =
            environmentFlagOrDefault("RECOVERY_NOTIFICATIONS_ENABLED", false);
        const bool localTtsEnabled =
            environmentFlagOrDefault("AI_LOCAL_TTS_ENABLED", false);
        try {
            pauseable::ActionRouterConfig routerConfig;
            routerConfig.repetitiveActionsEnabled = repetitiveActionsEnabled;
            routerConfig.wanderingActionsEnabled = wanderingActionsEnabled;
            routerConfig.recoveryNotificationsEnabled = recoveryNotificationsEnabled;
            routerConfig.repetitiveCooldown = std::chrono::seconds(
                environmentUnsignedOrDefault("REPETITIVE_ALERT_COOLDOWN_SECONDS", 900, 86400));
            routerConfig.wanderingCooldown = std::chrono::seconds(
                environmentUnsignedOrDefault("WANDERING_ALERT_COOLDOWN_SECONDS", 300, 86400));
            routerConfig.statePath = environmentOrDefault(
                "PAUSEABLE_ACTION_STATE_PATH",
                defaultRuntimeDataPath("action-router-state.json"));
            actionRouter = std::make_shared<pauseable::ActionRouter>(routerConfig);
            alog::logInfo(
                "ACTION_ROUTER_READY",
                "state={} states={} repetitive={} wandering={} recovery={} repetitive_cooldown={} wandering_cooldown={}",
                actionRouter->statePath(),
                actionRouter->stateCount(),
                repetitiveActionsEnabled,
                wanderingActionsEnabled,
                recoveryNotificationsEnabled,
                routerConfig.repetitiveCooldown.count(),
                routerConfig.wanderingCooldown.count());
        } catch (const std::exception& error) {
            pauseable::ActionRouterConfig failClosed;
            actionRouter = std::make_shared<pauseable::ActionRouter>(failClosed);
            alog::logError(
                "ACTION_ROUTER_FAIL_CLOSED",
                "Persistent state could not be loaded; all AI actions are blocked: {}",
                error.what());
        }

        std::shared_ptr<pauseable::DecisionGatewayClient> decisionGatewayClient;
        std::unique_ptr<pauseable::DecisionOutbox> decisionOutbox;
        const bool decisionGatewayEnabled =
            environmentFlagOrDefault("DECISION_GATEWAY_ENABLED", false);
        if (decisionGatewayEnabled) {
            try {
                pauseable::DecisionGatewayConfig gatewayConfig;
                gatewayConfig.eventUrl = environmentOrDefault(
                    "DECISION_GATEWAY_URL",
                    "https://pauseable-api.onrender.com/api/events/decisions");
                gatewayConfig.bearerToken = environmentOrDefault("PAUSEABLE_DEVICE_TOKEN", "");
                gatewayConfig.timeout = std::chrono::seconds(
                    environmentUnsignedOrDefault("DECISION_GATEWAY_TIMEOUT_SECONDS", 8, 60));
                decisionGatewayClient =
                    std::make_shared<pauseable::DecisionGatewayClient>(std::move(gatewayConfig));

                pauseable::DecisionOutboxConfig outboxConfig;
                outboxConfig.directory = environmentOrDefault(
                    "PAUSEABLE_DECISION_OUTBOX_DIR",
                    defaultRuntimeDataPath("decision-outbox"));
                outboxConfig.maximumPending = environmentUnsignedOrDefault(
                    "DECISION_OUTBOX_MAX_PENDING", 10000, 100000);
                outboxConfig.maximumAttempts = static_cast<unsigned int>(
                    environmentUnsignedOrDefault("DECISION_OUTBOX_MAX_ATTEMPTS", 3, 20));

                decisionOutbox = std::make_unique<pauseable::DecisionOutbox>(
                    outboxConfig,
                    [decisionGatewayClient](
                        const std::string& eventId,
                        const std::string& payload) {
                        return decisionGatewayClient->publish(eventId, payload);
                    },
                    [](const std::string& state,
                       const std::string& eventId,
                       unsigned int attempts,
                       const std::string& detail) {
                        if (state == "dead_letter" || state == "storage_error") {
                            alog::logError(
                                "DECISION_OUTBOX_STATUS",
                                "state={} event_id={} attempts={} detail={}",
                                state, eventId, attempts, detail);
                        } else if (state == "retry_scheduled") {
                            alog::logWarn(
                                "DECISION_OUTBOX_STATUS",
                                "state={} event_id={} attempts={} detail={}",
                                state, eventId, attempts, detail);
                        } else {
                            alog::logInfo(
                                "DECISION_OUTBOX_STATUS",
                                "state={} event_id={} attempts={} detail={}",
                                state, eventId, attempts, detail);
                        }
                    });
                decisionOutbox->start();
                alog::logInfo(
                    "DECISION_GATEWAY_READY",
                    "outbox={} pending={} dead_letters={} timeout_seconds={}",
                    decisionOutbox->directory(),
                    decisionOutbox->pendingCount(),
                    decisionOutbox->deadLetterCount(),
                    environmentUnsignedOrDefault("DECISION_GATEWAY_TIMEOUT_SECONDS", 8, 60));
            } catch (const std::exception& error) {
                decisionOutbox.reset();
                decisionGatewayClient.reset();
                alog::logError(
                    "DECISION_GATEWAY_FAIL_CLOSED",
                    "Guardian forwarding remains disabled: {}",
                    error.what());
            }
        } else {
            alog::logInfo(
                "DECISION_GATEWAY_DISABLED",
                "Set DECISION_GATEWAY_ENABLED=1 with PAUSEABLE_DEVICE_TOKEN after endpoint validation");
        }

        std::unique_ptr<pauseable::MqttDecisionSubscriber> mqttDecisionSubscriber;
        if (environmentFlagOrDefault("MQTT_DECISIONS_ENABLED", true)) {
            try {
                pauseable::BehaviorValidationConfig validationConfig;
                validationConfig.patientId = environmentOrDefault("PAUSEABLE_PATIENT_ID", "byunwoojin");
                validationConfig.deviceId = environmentOrDefault("PAUSEABLE_DEVICE_ID", "pi5-home-01");
                validationConfig.staleAfter = std::chrono::seconds(
                    environmentUnsignedOrDefault("MQTT_STALE_SECONDS", 300, 86400));
                validationConfig.maximumFutureSkew = std::chrono::seconds(
                    environmentUnsignedOrDefault("MQTT_FUTURE_SKEW_SECONDS", 30, 3600));

                auto eventLedger = std::make_shared<pauseable::EventLedger>(
                    environmentOrDefault("PAUSEABLE_EVENT_LEDGER_PATH", defaultEventLedgerPath()),
                    10000,
                    std::chrono::hours(24));

                pauseable::MqttDecisionSubscriberConfig mqttConfig;
                mqttConfig.host = environmentOrDefault("MQTT_HOST", "127.0.0.1");
                mqttConfig.port = static_cast<std::uint16_t>(
                    environmentUnsignedOrDefault("MQTT_PORT", 1883, 65535));
                mqttConfig.clientId = environmentOrDefault(
                    "MQTT_CLIENT_ID", "pauseable-central-pi5-home-01");
                mqttConfig.username = environmentOrDefault("MQTT_USER", "");
                mqttConfig.password = environmentOrDefault("MQTT_PASSWORD", "");

                mqttDecisionSubscriber =
                    std::make_unique<pauseable::MqttDecisionSubscriber>(
                        mqttConfig,
                        [validationConfig, eventLedger, actionRouter,
                         outbox = decisionOutbox.get(), ttsEngine,
                         localTtsEnabled](const pauseable::MqttDecisionMessage& message) {
                            if (message.qos != 1 || message.retained) {
                                alog::logWarn(
                                    "MQTT_DECISION_REJECTED",
                                    "topic={} reason={} qos={} retained={}",
                                    message.topic,
                                    message.qos != 1 ? "qos_must_be_1" : "retained_message",
                                    message.qos,
                                    message.retained);
                                return;
                            }

                            const auto validation = pauseable::validateBehaviorInference(
                                message.topic, message.payload, validationConfig);
                            if (validation.disposition !=
                                pauseable::ValidationDisposition::Accepted) {
                                alog::logWarn(
                                    "MQTT_DECISION_REJECTED",
                                    "topic={} disposition={} reason={}",
                                    message.topic,
                                    static_cast<int>(validation.disposition),
                                    validation.detail);
                                return;
                            }

                            const auto& inference = *validation.inference;
                            const auto ledgerResult = eventLedger->inspect(
                                inference.eventId, inference.canonicalPayload);
                            if (ledgerResult == pauseable::EventLedger::Result::Duplicate) {
                                alog::logInfo(
                                    "MQTT_DECISION_DUPLICATE",
                                    "event_id={} source={} action=ignored",
                                    inference.eventId,
                                    pauseable::toString(inference.source));
                                return;
                            }
                            if (ledgerResult == pauseable::EventLedger::Result::Conflict) {
                                alog::logError(
                                    "MQTT_DECISION_CONFLICT",
                                    "event_id={} source={} action=blocked",
                                    inference.eventId,
                                    pauseable::toString(inference.source));
                                return;
                            }

                            const auto decision = pauseable::toDecision(inference);
                            const auto actionPlan = actionRouter->route(decision);

                            alog::logInfo(
                                "CENTRAL_DECISION_ACCEPTED",
                                "event_id={} source={} decision={} risk={} score={}",
                                decision.eventId,
                                decision.source,
                                pauseable::toString(decision.type),
                                pauseable::toString(decision.risk),
                                decision.riskScore
                                    ? std::to_string(*decision.riskScore)
                                    : std::string("null"));
                            alog::logInfo(
                                "CENTRAL_ACTION_ROUTED",
                                "event_id={} disposition={} reason={} notify={} speak={} control={}",
                                decision.eventId,
                                pauseable::toString(actionPlan.disposition),
                                actionPlan.reason,
                                actionPlan.notifyGuardian,
                                actionPlan.speakLocal,
                                actionPlan.controlAppliance);

                            if (actionPlan.notifyGuardian) {
                                if (outbox != nullptr) {
                                    try {
                                        const auto enqueueResult = outbox->enqueue(
                                            decision.eventId,
                                            pauseable::makeDecisionEventPayload(inference, actionPlan));
                                        alog::logInfo(
                                            "CENTRAL_GUARDIAN_QUEUED",
                                            "event_id={} result={}",
                                            decision.eventId,
                                            enqueueResult == pauseable::OutboxEnqueueResult::Enqueued
                                                ? "enqueued" : "already_pending");
                                    } catch (const std::exception& error) {
                                        alog::logError(
                                            "CENTRAL_GUARDIAN_QUEUE_FAILED",
                                            "event_id={} detail={}",
                                            decision.eventId,
                                            error.what());
                                        throw;
                                    }
                                } else {
                                    alog::logWarn(
                                        "CENTRAL_GUARDIAN_BLOCKED",
                                        "event_id={} reason=gateway_disabled",
                                        decision.eventId);
                                }
                            }

                            if (actionPlan.speakLocal && localTtsEnabled && ttsEngine) {
                                const bool playYoutube =
                                    environmentFlagOrDefault("PAUSEABLE_YOUTUBE_ENABLED", false) &&
                                    actionPlan.disposition == pauseable::ActionDisposition::Execute &&
                                    inference.inferenceStatus == pauseable::InferenceStatus::Ok &&
                                    decision.source == "repetitive-ai" &&
                                    decision.type == pauseable::DecisionType::RepetitiveBehavior &&
                                    (
                                        decision.risk == pauseable::RiskLevel::Caution ||
                                        decision.risk == pauseable::RiskLevel::Danger
                                    );

                                pauseable::PiperTtsEngine::CompletionHandler onCompleted;

                                if (playYoutube) {
                                    onCompleted = [eventId = decision.eventId] {
                                        if (requestYoutubePlayback()) {
                                            alog::logInfo(
                                                "CENTRAL_YOUTUBE_REQUEST_SENT",
                                                "event_id={}",
                                                eventId
                                            );
                                        } else {
                                            alog::logWarn(
                                                "CENTRAL_YOUTUBE_REQUEST_FAILED",
                                                "event_id={} reason=request_channel_unavailable",
                                                eventId
                                            );
                                        }
                                    };
                                }

                                ttsEngine->speak(decision.message, onCompleted);

                                alog::logInfo(
                                    "CENTRAL_LOCAL_TTS_QUEUED",
                                    "event_id={} decision={}",
                                    decision.eventId,
                                    pauseable::toString(decision.type)
                                );
                            }

                            const auto committed = eventLedger->record(
                                inference.eventId, inference.canonicalPayload);
                            if (committed != pauseable::EventLedger::Result::NewEvent) {
                                alog::logWarn(
                                    "MQTT_DECISION_COMMIT_RACE",
                                    "event_id={} result={}",
                                    inference.eventId,
                                    committed == pauseable::EventLedger::Result::Duplicate
                                        ? "duplicate" : "conflict");
                            }
                        },
                        [](const std::string& state, const std::string& detail) {
                            if (state == "disconnected") {
                                alog::logWarn(
                                    "MQTT_DECISION_STATUS",
                                    "state={} detail={}", state, detail);
                            } else if (state != "ping") {
                                alog::logInfo(
                                    "MQTT_DECISION_STATUS",
                                    "state={} detail={}", state, detail);
                            }
                        });
                mqttDecisionSubscriber->start();
                alog::logInfo(
                    "MQTT_DECISION_STARTED",
                    "topics=2 ledger={} ledger_entries={} repetitive_actions={} wandering_actions={} local_tts={}",
                    eventLedger->path(),
                    eventLedger->size(),
                    repetitiveActionsEnabled,
                    wanderingActionsEnabled,
                    localTtsEnabled);
            } catch (const std::exception& error) {
                alog::logError(
                    "MQTT_DECISION_START_FAILED",
                    "Decision subscriber could not start: {}",
                    error.what());
            }
        } else {
            alog::logInfo(
                "MQTT_DECISION_DISABLED",
                "Set MQTT_DECISIONS_ENABLED=1 to enable intake");
        }

        std::unique_ptr<pauseable::HaEntityClient> haClient;
        const char* accessToken = std::getenv("HA_TOKEN");
        if (accessToken == nullptr || std::string(accessToken).empty()) {
            alog::logWarn(
                "HA_DISABLED",
                "HA_TOKEN is not set; Home Assistant integration will remain disabled"
            );
        } else {
            try {
                const char* configuredPath = std::getenv("HA_CONFIG_PATH");
                const std::string configPath =
                    configuredPath == nullptr || std::string(configuredPath).empty()
                        ? "config/ha_config.json"
                        : configuredPath;
                const HaRuntimeConfig haConfig = loadHaRuntimeConfig(configPath);
                const bool rawHaActionsEnabled =
                    environmentFlagOrDefault("RAW_HA_ACTIONS_ENABLED", false);

                haClient = std::make_unique<pauseable::HaEntityClient>(
                    haConfig.websocketUrl,
                    accessToken,
                    haConfig.entityIds,
                    [gatewayClient, ttsEngine, rawHaActionsEnabled](
                        const pauseable::HaEntityEvent& event) {
                        alog::logInfo(
                            "HA_ENTITY_EVENT",
                            "entity={}, previous={}, state={}, occurred_at={}",
                            event.entityId,
                            event.previousState.value_or("<none>"),
                            event.state,
                            event.occurredAt
                        );

                        if (!event.previousState.has_value() ||
                            *event.previousState == event.state) {
                            return;
                        }

                        if (!rawHaActionsEnabled) {
                            alog::logInfo(
                                "RAW_HA_ACTION_BLOCKED",
                                "entity={} reason=AI_decision_route_required",
                                event.entityId);
                            return;
                        }

                        if (ttsEngine) {
                            ttsEngine->speak(ttsMessageFor(event));
                        }

                        if (!gatewayClient) {
                            return;
                        }

                        try {
                            const auto result = gatewayClient->publish(event);
                            alog::logInfo(
                                "GATEWAY_EVENT_SENT",
                                "status={}, alert={}, voice_status={}, audio_url={}",
                                result.status,
                                result.alertTitle,
                                result.voiceStatus,
                                result.audioUrl.empty() ? "<none>" : result.audioUrl
                            );
                        } catch (const std::exception& error) {
                            alog::logError(
                                "GATEWAY_EVENT_FAILED",
                                "Failed to forward HA event: {}",
                                error.what()
                            );
                        }
                    }
                );
                haClient->start();

                alog::logInfo(
                    "HA_STARTED",
                    "Home Assistant client started for {} configured entities; raw_actions={}",
                    haConfig.entityIds.size(),
                    rawHaActionsEnabled
                );
            } catch (const std::exception& error) {
                alog::logError(
                    "HA_START_FAILED",
                    "Home Assistant client could not start: {}",
                    error.what()
                );
            }
        }

#ifndef USE_SD_EVENT
        usePropertyManagerWithObserver(connection);

        std::signal(SIGINT, signalHandler);
        std::signal(SIGTERM, signalHandler);

        connection->enterEventLoopAsync();
        while (!g_stop_requested) {
            std::this_thread::sleep_for(std::chrono::seconds(1));
        }
        connection->leaveEventLoop();
#else
        __attribute__((cleanup(sd_event_unrefp))) sd_event* event = nullptr;
        __attribute__((cleanup(sd_event_source_unrefp))) sd_event_source* timer = nullptr;

        sd_event_default(&event);


        sd_event_add_time_relative(
            event,
            &timer,
            CLOCK_MONOTONIC,
            1000000,
            0,
            [](sd_event_source*, uint64_t, void*) {
                alog::logInfo("TIMER_EXPIRED", "Timer expired after 1 second");
                return 0;
            },
            nullptr
        );

        usePropertyManagerWithObserver(connection);


        auto manualProxy = sdbus::createProxy(
            *connection,
            sdbus::ServiceName("org.freedesktop.DBus"),
            sdbus::ObjectPath("/org/freedesktop/DBus")
        );
        const std::string wellKnownName = "com.atlas.PropertyManager1";
        std::string response;
        try {
            manualProxy->callMethod("GetNameOwner")
                .onInterface("org.freedesktop.DBus")
                .withArguments(wellKnownName)
                .storeResultsTo(response);
            alog::logInfo("DBUS_GETNAMEOWNER", "GetNameOwner response: {} = {}", wellKnownName, response);
        } catch (const std::exception& e) {
            alog::logError("DBUS_GETNAMEOWNER", "Failed to call GetNameOwner: {}", e.what());
        }

        connection->attachSdEventLoop(event);

        struct sigaction action = {};
        action.sa_handler = signalHandler;
        action.sa_flags = 0;
        sigemptyset(&action.sa_mask);

        if (sigaction(SIGINT, &action, nullptr) < 0 || sigaction(SIGTERM, &action, nullptr) < 0) {
            alog::logWarn("SIGNAL_SETUP", "Failed to set up signal handlers");
        }

        while (!g_stop_requested) {
            const int result = sd_event_run(event, 100000);
            if (result < 0 && result != -EINTR) {
                alog::logError("APP_EVENTLOOP", "Failed to run event loop: {}", strerror(-result));
                return 1;
            }
        }
#endif
    } catch (const std::exception& e) {
        alog::logError("APP_EXCEPTION", "Exception: {}", e.what());
        return 1;
    }

    alog::logInfo("APP_EXIT", "Application stopped");
    return 0;
}
