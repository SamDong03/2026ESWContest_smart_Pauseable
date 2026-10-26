#pragma once

#include <optional>
#include <string>

namespace pauseable {

struct HaEntityEvent
{
    std::string eventId;
    std::string occurredAt;
    std::string source{"home-assistant"};
    std::string entityId;
    std::string state;
    std::optional<std::string> previousState;
    std::string attributesJson{"{}"};
};

}
