#pragma once

#include <chrono>
#include <string>

#include "HaEntityEvent.hpp"

namespace pauseable {

struct GatewayPublishResult
{
    std::string status;
    std::string alertTitle;
    std::string voiceStatus;
    std::string audioUrl;
};

struct GatewayConfig
{
    std::string eventUrl;
    std::string bearerToken;
    std::string patientId;
    std::chrono::seconds timeout{8};
};

class GatewayClient
{
public:
    explicit GatewayClient(GatewayConfig config);

    GatewayPublishResult publish(const HaEntityEvent& event) const;

private:
    GatewayConfig config_;
};

}
