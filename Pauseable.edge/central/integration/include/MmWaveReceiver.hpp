#pragma once
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <nlohmann/json.hpp>

namespace pauseable {
struct MmWaveReceiverConfig {
    std::string bindAddress = "127.0.0.1";
    std::uint16_t port = 5005;
    std::uint64_t staleAfterMs = 3000;
    std::uint64_t summaryEveryMs = 1000;
    std::string allowPeer;
    unsigned maxPacketsPerSecond = 200;
};


class MmWaveReceiver {
public:
    using Reporter = std::function<void(const nlohmann::json&)>;
    explicit MmWaveReceiver(MmWaveReceiverConfig config, Reporter reporter);
    ~MmWaveReceiver();
    MmWaveReceiver(const MmWaveReceiver&) = delete;
    MmWaveReceiver& operator=(const MmWaveReceiver&) = delete;
    void start();
    void stop() noexcept;
    bool running() const noexcept;
    std::uint16_t boundPort() const noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
