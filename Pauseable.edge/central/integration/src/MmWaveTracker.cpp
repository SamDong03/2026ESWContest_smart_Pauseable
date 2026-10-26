#include "MmWaveTracker.hpp"

#include <limits>
#include <stdexcept>

namespace pauseable {
namespace {

std::uint64_t saturatedAdd(std::uint64_t left, std::uint64_t right)
{
    const auto maximum = std::numeric_limits<std::uint64_t>::max();
    return maximum - left < right ? maximum : left + right;
}

void increment(std::uint64_t& counter, std::uint64_t amount = 1)
{
    counter = saturatedAdd(counter, amount);
}

std::uint64_t elapsed(std::uint64_t now, std::uint64_t before)
{

    return now >= before ? now - before : 0;
}

}

MmWaveTracker::MmWaveTracker(MmWaveTrackerConfig config) : config_(config)
{
    if (config_.staleAfterMs == 0 || config_.maxStreams == 0 ||
        config_.maxRetiredSessions == 0) {
        throw std::invalid_argument("mmWave tracker limits and stale threshold must be positive");
    }
}

nlohmann::json MmWaveTracker::countersJson(const Counters& counters)
{
    return {
        {"accepted", counters.accepted},
        {"duplicate", counters.duplicate},
        {"out_of_order", counters.outOfOrder},
        {"old_session", counters.oldSession},
        {"uptime_regression", counters.uptimeRegression},
        {"stream_limit", counters.streamLimit},
        {"session_limit", counters.sessionLimit},
        {"sequence_gaps_observed", counters.sequenceGapsObserved},
    };
}

void MmWaveTracker::rememberSequence(Stream& stream, std::uint32_t sequence)
{
    if (!stream.recentSeq.insert(sequence).second) {
        return;
    }
    stream.recentSeqOrder.push_back(sequence);
    if (stream.recentSeqOrder.size() > recentSequenceCapacity) {
        stream.recentSeq.erase(stream.recentSeqOrder.front());
        stream.recentSeqOrder.pop_front();
    }
}

nlohmann::json MmWaveTracker::streamJson(const StreamKey& key,
                                        const Stream& stream,
                                        std::uint64_t nowMonoMs) const
{
    const auto receiverAgeMs = elapsed(nowMonoMs, stream.receivedMonoMs);
    const auto& sensorStatus = stream.lastEvent.at("sensor_status").get_ref<const std::string&>();
    nlohmann::json frameAge = nullptr;
    if (sensorStatus == "ok") {
        frameAge = saturatedAdd(stream.lastEvent.at("frame_age_ms").get<std::uint64_t>(),
                                receiverAgeMs);
    }

    std::string quality;
    if (receiverAgeMs >= config_.staleAfterMs) {
        quality = "silent";
    } else if (sensorStatus == "error") {
        quality = "sensor_error";
    } else if (sensorStatus == "disconnected") {
        quality = "disconnected";
    } else if (frameAge.get<std::uint64_t>() >= config_.staleAfterMs) {
        quality = "stale_frame";
    } else {
        quality = "fresh";
    }

    std::string observation = "unknown";
    if (quality == "fresh") {
        observation = stream.lastEvent.at("target_count").get<unsigned>() == 0
                          ? "no_target_detected"
                          : "target_detected";
    }

    return {
        {"data_origin", key.first},
        {"sensor_id", key.second},
        {"session_id", stream.sessionId},
        {"last_seq", stream.lastSeq},
        {"received_at", stream.receivedUtc},
        {"received_mono_ms", stream.receivedMonoMs},
        {"peer", stream.peer},
        {"receiver_age_ms", receiverAgeMs},
        {"effective_frame_age_ms", frameAge},
        {"quality", quality},
        {"observation", observation},
        {"retired_session_count", stream.retiredSessions.size()},
        {"recent_sequence_count", stream.recentSeq.size()},
        {"last_event", stream.lastEvent},
        {"counters", countersJson(stream.counters)},
    };
}

nlohmann::json MmWaveTracker::ingest(const nlohmann::json& event,
                                    std::uint64_t receivedMonoMs,
                                    const std::string& receivedUtc,
                                    const std::string& peer)
{
    const StreamKey key{event.at("data_origin").get<std::string>(),
                        event.at("sensor_id").get<std::string>()};
    const auto sessionId = event.at("session_id").get<std::string>();
    const auto seq = event.at("seq").get<std::uint32_t>();
    const auto uptimeMs = event.at("uptime_ms").get<std::uint64_t>();
    nlohmann::json report = {
        {"kind", "mmwave_rejected"},
        {"accepted", false},
        {"data_origin", key.first},
        {"sensor_id", key.second},
        {"session_id", sessionId},
        {"seq", seq},
        {"received_at", receivedUtc},
        {"received_mono_ms", receivedMonoMs},
        {"peer", peer},
    };

    auto found = streams_.find(key);
    const bool newStream = found == streams_.end();
    if (newStream && streams_.size() >= config_.maxStreams) {
        increment(counters_.streamLimit);
        report["reason"] = "stream_limit";
        return report;
    }
    if (newStream) {
        found = streams_.emplace(key, Stream{}).first;
    }
    auto& stream = found->second;
    const bool sessionChanged = !newStream && stream.sessionId != sessionId;

    auto reject = [&](const char* reason, std::uint64_t Counters::*counter) {
        increment(counters_.*counter);
        increment(stream.counters.*counter);
        report["reason"] = reason;
        return report;
    };

    if (sessionChanged) {
        if (stream.retiredSessions.count(sessionId) != 0) {
            return reject("old_session", &Counters::oldSession);
        }


        if (stream.retiredSessions.size() >= config_.maxRetiredSessions) {
            return reject("session_limit", &Counters::sessionLimit);
        }
        stream.retiredSessions.insert(stream.sessionId);
        stream.recentSeq.clear();
        stream.recentSeqOrder.clear();
    } else if (!newStream) {
        if (seq <= stream.lastSeq) {
            if (seq == stream.lastSeq || stream.recentSeq.count(seq) != 0) {
                return reject("duplicate", &Counters::duplicate);
            }


            rememberSequence(stream, seq);
            return reject("out_of_order", &Counters::outOfOrder);
        }
        if (uptimeMs < stream.lastUptimeMs) {
            return reject("uptime_regression", &Counters::uptimeRegression);
        }
        const auto gaps = static_cast<std::uint64_t>(seq) - stream.lastSeq - 1;
        increment(counters_.sequenceGapsObserved, gaps);
        increment(stream.counters.sequenceGapsObserved, gaps);
    }


    stream.sessionId = sessionId;
    stream.lastSeq = seq;
    stream.lastUptimeMs = uptimeMs;
    stream.receivedMonoMs = receivedMonoMs;
    stream.receivedUtc = receivedUtc;
    stream.peer = peer;
    stream.lastEvent = event;
    rememberSequence(stream, seq);
    increment(counters_.accepted);
    increment(stream.counters.accepted);

    report["kind"] = "mmwave_event";
    report["accepted"] = true;
    report["reason"] = "accepted";
    report["new_stream"] = newStream;
    report["session_changed"] = sessionChanged;
    report["event"] = event;
    report["stream"] = streamJson(key, stream, receivedMonoMs);
    return report;
}

nlohmann::json MmWaveTracker::snapshot(std::uint64_t nowMonoMs) const
{
    auto streams = nlohmann::json::array();
    for (const auto& entry : streams_) {
        streams.push_back(streamJson(entry.first, entry.second, nowMonoMs));
    }
    return {
        {"kind", "mmwave_snapshot"},
        {"snapshot_mono_ms", nowMonoMs},
        {"stale_after_ms", config_.staleAfterMs},
        {"stream_count", streams_.size()},
        {"streams", std::move(streams)},
        {"counters", countersJson(counters_)},
    };
}

}
