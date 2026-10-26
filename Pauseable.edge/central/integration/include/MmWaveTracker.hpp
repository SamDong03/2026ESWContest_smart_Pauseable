#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <map>
#include <string>
#include <unordered_set>
#include <utility>

#include <nlohmann/json.hpp>

namespace pauseable {

struct MmWaveTrackerConfig
{
    std::uint64_t staleAfterMs = 3000;
    std::size_t maxStreams = 64;
    std::size_t maxRetiredSessions = 64;
};


class MmWaveTracker
{
public:
    explicit MmWaveTracker(MmWaveTrackerConfig config = {});

    nlohmann::json ingest(const nlohmann::json& validatedEvent,
                          std::uint64_t receivedMonoMs,
                          const std::string& receivedUtc,
                          const std::string& peer);
    nlohmann::json snapshot(std::uint64_t nowMonoMs) const;

private:
    struct Counters
    {
        std::uint64_t accepted = 0;
        std::uint64_t duplicate = 0;
        std::uint64_t outOfOrder = 0;
        std::uint64_t oldSession = 0;
        std::uint64_t uptimeRegression = 0;
        std::uint64_t streamLimit = 0;
        std::uint64_t sessionLimit = 0;
        std::uint64_t sequenceGapsObserved = 0;
    };

    struct Stream
    {
        std::string sessionId;
        std::unordered_set<std::string> retiredSessions;
        std::deque<std::uint32_t> recentSeqOrder;
        std::unordered_set<std::uint32_t> recentSeq;
        std::uint32_t lastSeq = 0;
        std::uint64_t lastUptimeMs = 0;
        std::uint64_t receivedMonoMs = 0;
        std::string receivedUtc;
        std::string peer;
        nlohmann::json lastEvent;
        Counters counters;
    };

    using StreamKey = std::pair<std::string, std::string>;
    static constexpr std::size_t recentSequenceCapacity = 1024;

    static nlohmann::json countersJson(const Counters& counters);
    static void rememberSequence(Stream& stream, std::uint32_t sequence);
    nlohmann::json streamJson(const StreamKey& key,
                              const Stream& stream,
                              std::uint64_t nowMonoMs) const;

    MmWaveTrackerConfig config_;
    Counters counters_;
    std::map<StreamKey, Stream> streams_;
};

}
