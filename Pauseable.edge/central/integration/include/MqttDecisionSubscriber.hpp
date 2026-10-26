#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace pauseable {

struct MqttDecisionSubscriberConfig {
    std::string host{"127.0.0.1"};
    std::uint16_t port{1883};
    std::string clientId{"pauseable-central-pi5-home-01"};
    std::string username;
    std::string password;
    std::vector<std::string> topics{
        "pauseable/ai/repetitive/decision",
        "pauseable/ai/wandering/decision"
    };
    std::uint16_t keepAliveSeconds{60};
};

struct MqttDecisionMessage {
    std::string topic;
    std::string payload;
    int qos{};
    bool retained{};
    bool duplicate{};
};

class MqttDecisionSubscriber {
public:
    using MessageHandler = std::function<void(const MqttDecisionMessage&)>;
    using StatusHandler = std::function<void(const std::string&, const std::string&)>;

    MqttDecisionSubscriber(
        MqttDecisionSubscriberConfig config,
        MessageHandler messageHandler,
        StatusHandler statusHandler);
    ~MqttDecisionSubscriber();

    MqttDecisionSubscriber(const MqttDecisionSubscriber&) = delete;
    MqttDecisionSubscriber& operator=(const MqttDecisionSubscriber&) = delete;

    void start();
    void stop() noexcept;
    bool running() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}
