#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>

#include <nlohmann/json.hpp>

namespace pauseable {

struct MmWaveArchiveConfig {
    std::string directory;
    std::uint64_t sampleEveryMs = 5000;
    std::uint64_t maxTotalBytes = 48ULL * 1024ULL * 1024ULL;
    std::uint32_t maxRetentionDays = 7;
    std::size_t maxQueuedRecords = 256;
};

class MmWaveArchive {
public:
    using Reporter = std::function<void(const nlohmann::json&)>;

    explicit MmWaveArchive(MmWaveArchiveConfig config, Reporter reporter);
    ~MmWaveArchive();

    MmWaveArchive(const MmWaveArchive&) = delete;
    MmWaveArchive& operator=(const MmWaveArchive&) = delete;

    void start();
    void submit(const nlohmann::json& receiverReport) noexcept;
    void stop() noexcept;
    bool running() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}
