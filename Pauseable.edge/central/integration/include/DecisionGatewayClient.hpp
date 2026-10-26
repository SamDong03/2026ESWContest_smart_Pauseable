#pragma once

#include <chrono>
#include <string>

#include "DecisionOutbox.hpp"

namespace pauseable {

struct DecisionGatewayConfig {
    std::string eventUrl;
    std::string bearerToken;
    std::chrono::seconds timeout{8};
};

class DecisionGatewayClient {
public:
    explicit DecisionGatewayClient(DecisionGatewayConfig config);

    OutboxDeliveryResult publish(
        const std::string& eventId,
        const std::string& payload) const;

private:
    DecisionGatewayConfig config_;
};

}
