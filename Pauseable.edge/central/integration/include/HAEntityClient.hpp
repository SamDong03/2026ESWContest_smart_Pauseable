#pragma once

#include <functional>
#include <memory>
#include <string>
#include <vector>

#include "HaEntityEvent.hpp"

namespace pauseable {

class HaEntityClient
{
public:
    using EventHandler = std::function<void(const HaEntityEvent&)>;

    HaEntityClient(
        std::string websocketUrl,
        std::string accessToken,
        std::vector<std::string> entityIds,
        EventHandler eventHandler
    );

    ~HaEntityClient();

    HaEntityClient(const HaEntityClient&) = delete;
    HaEntityClient& operator=(const HaEntityClient&) = delete;

    void start();
    void stop();

    bool isRunning() const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}
