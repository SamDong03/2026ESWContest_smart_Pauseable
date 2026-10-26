#include "MmWaveTracker.hpp"

#include <cstdint>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using nlohmann::json;
using pauseable::MmWaveTracker;
using pauseable::MmWaveTrackerConfig;

#define CHECK(expression)                                                        \
    do {                                                                         \
        if (!(expression)) {                                                     \
            throw std::runtime_error(std::string("line ") +                     \
                                     std::to_string(__LINE__) + ": " #expression); \
        }                                                                        \
    } while (false)

json event(std::uint32_t seq = 0, std::uint64_t uptime = 100,
           const std::string& session = "session-a",
           const std::string& origin = "simulated",
           const std::string& sensor = "test-radar")
{
    const auto source = origin == "live" ? "esp32-ld6004"
                        : origin == "replay" ? "pauseable-replay"
                                             : "pauseable-simulator";
    json replay = nullptr;
    if (origin == "replay") {
        replay = {{"log_id", "test-log"}, {"frame_index", seq},
                  {"original_origin", "simulated"},
                  {"original_event_id", "test-radar:source-session:" + std::to_string(seq)},
                  {"original_occurred_at", nullptr}};
    }
    return {
        {"schema_version", "1.0"},
        {"event_id", sensor + ":" + session + ":" + std::to_string(seq)},
        {"source", source}, {"data_origin", origin},
        {"sensor_id", sensor}, {"session_id", session}, {"seq", seq},
        {"occurred_at", nullptr}, {"time_status", "unsynced"},
        {"uptime_ms", uptime}, {"measurement_profile", "ld6004-target-raw-v1"},
        {"sensor_status", "ok"}, {"frame_age_ms", 0}, {"target_count", 1},
        {"targets_truncated", false},
        {"targets", json::array({{{"id", 1}, {"x", 0.1}, {"y", 0.2},
                                   {"z", 0.3}, {"doppler", -1}}})},
        {"replay", replay},
    };
}

json ingest(MmWaveTracker& tracker, const json& value, std::uint64_t received = 100)
{
    return tracker.ingest(value, received, "2026-09-08T01:02:03Z", "127.0.0.1:5006");
}

json first(const MmWaveTracker& tracker, std::uint64_t now = 100)
{
    return tracker.snapshot(now).at("streams").at(0);
}

void initialState()
{
    MmWaveTracker tracker;
    const auto snapshot = tracker.snapshot(0);
    CHECK(snapshot.at("kind") == "mmwave_snapshot");
    CHECK(snapshot.at("streams").empty());
    CHECK(snapshot.at("counters").at("accepted") == 0);
}

void preservesSourceAndReceiverTimes()
{
    MmWaveTracker tracker;
    auto original = event();
    const auto report = ingest(tracker, original, 123);
    CHECK(report.at("kind") == "mmwave_event");
    CHECK(report.at("accepted") == true);
    CHECK(report.at("event") == original);
    CHECK(report.at("received_at") == "2026-09-08T01:02:03Z");
    CHECK(report.at("received_mono_ms") == 123);
    CHECK(first(tracker, 123).at("last_event").at("occurred_at").is_null());
    CHECK(first(tracker, 123).at("peer") == "127.0.0.1:5006");
}

void firstHighSequenceDoesNotClaimLoss()
{
    MmWaveTracker tracker;
    CHECK(ingest(tracker, event(150)).at("accepted") == true);
    CHECK(tracker.snapshot(100).at("counters").at("sequence_gaps_observed") == 0);
}

void duplicateDoesNotRefreshOrReplace()
{
    MmWaveTracker tracker;
    const auto original = event();
    ingest(tracker, original, 100);
    auto altered = original;
    altered["targets"][0]["x"] = 999;
    const auto report = ingest(tracker, altered, 3000);
    CHECK(report.at("kind") == "mmwave_rejected");
    CHECK(report.at("reason") == "duplicate");
    CHECK(report.at("received_mono_ms") == 3000);
    const auto summary = first(tracker, 3100);
    CHECK(summary.at("received_mono_ms") == 100);
    CHECK(summary.at("last_event") == original);
    CHECK(summary.at("quality") == "silent");
    CHECK(summary.at("observation") == "unknown");
}

void lateThenRepeatedLateIsDuplicate()
{
    MmWaveTracker tracker;
    ingest(tracker, event(10), 100);
    CHECK(ingest(tracker, event(8), 110).at("reason") == "out_of_order");
    CHECK(ingest(tracker, event(8), 120).at("reason") == "duplicate");
    CHECK(first(tracker).at("last_seq") == 10);
    CHECK(first(tracker).at("received_mono_ms") == 100);
}

void observedHolesAreNotGuaranteedLoss()
{
    MmWaveTracker tracker;
    ingest(tracker, event(0, 100));
    ingest(tracker, event(3, 101));
    CHECK(ingest(tracker, event(2, 100)).at("reason") == "out_of_order");
    const auto counters = tracker.snapshot(100).at("counters");
    CHECK(counters.at("sequence_gaps_observed") == 2);
    CHECK(counters.at("out_of_order") == 1);
    CHECK(counters.at("accepted") == 2);
}

void uptimeRegressionRejectedAndEqualAllowed()
{
    MmWaveTracker tracker;
    ingest(tracker, event(0, 500), 100);
    CHECK(ingest(tracker, event(1, 499), 200).at("reason") == "uptime_regression");
    CHECK(first(tracker).at("received_mono_ms") == 100);
    CHECK(ingest(tracker, event(1, 500), 201).at("accepted") == true);
    CHECK(first(tracker, 201).at("last_seq") == 1);
}

void sessionRestartRetiresOldSession()
{
    MmWaveTracker tracker;
    ingest(tracker, event(100, 10000), 100);
    auto report = ingest(tracker, event(0, 0, "session-b"), 200);
    CHECK(report.at("accepted") == true);
    CHECK(report.at("session_changed") == true);
    CHECK(ingest(tracker, event(101, 10001), 300).at("reason") == "old_session");
    CHECK(first(tracker, 3200).at("quality") == "silent");
    CHECK(first(tracker, 200).at("retired_session_count") == 1);
    CHECK(first(tracker, 200).at("session_id") == "session-b");
    CHECK(first(tracker, 200).at("counters").at("sequence_gaps_observed") == 0);
}

void retiredSessionLimitIsFailClosed()
{
    MmWaveTracker tracker({3000, 64, 1});
    ingest(tracker, event(0, 0, "session-a"), 100);
    ingest(tracker, event(0, 0, "session-b"), 200);
    CHECK(ingest(tracker, event(0, 0, "session-c"), 300).at("reason") == "session_limit");
    CHECK(ingest(tracker, event(1, 100, "session-a"), 400).at("reason") == "old_session");
    CHECK(first(tracker, 400).at("session_id") == "session-b");
    CHECK(first(tracker, 400).at("received_mono_ms") == 200);
    CHECK(first(tracker, 400).at("retired_session_count") == 1);
}

void separatesOriginsAndSensors()
{
    MmWaveTracker tracker;
    for (const auto& origin : {"live", "simulated", "replay"}) {
        CHECK(ingest(tracker, event(0, 100, "session-a", origin)).at("accepted") == true);
    }
    CHECK(ingest(tracker, event(0, 100, "session-a", "live", "other-radar")).at("accepted") == true);
    const auto snapshot = tracker.snapshot(100);
    CHECK(snapshot.at("stream_count") == 4);
    for (const auto& stream : snapshot.at("streams")) {
        CHECK(stream.at("counters").at("accepted") == 1);
    }
}

void streamLimitDoesNotEvictExisting()
{
    MmWaveTracker tracker({3000, 1, 64});
    ingest(tracker, event(), 100);
    CHECK(ingest(tracker, event(0, 100, "session-a", "live"), 200).at("reason") == "stream_limit");
    CHECK(ingest(tracker, event(1, 101), 300).at("accepted") == true);
    CHECK(tracker.snapshot(300).at("stream_count") == 1);
    CHECK(tracker.snapshot(300).at("counters").at("stream_limit") == 1);
}

void receiverTimeoutBoundary()
{
    MmWaveTracker tracker({1000, 64, 64});
    ingest(tracker, event(), 100);
    CHECK(first(tracker, 1099).at("quality") == "fresh");
    CHECK(first(tracker, 1100).at("quality") == "silent");
    CHECK(first(tracker, 1100).at("observation") == "unknown");
}

void emptyFrameIsOnlyNoTargetDetected()
{
    MmWaveTracker tracker;
    auto value = event();
    value["target_count"] = 0;
    value["targets"] = json::array();
    ingest(tracker, value);
    CHECK(first(tracker).at("quality") == "fresh");
    CHECK(first(tracker).at("observation") == "no_target_detected");
    CHECK(first(tracker, 3100).at("observation") == "unknown");
}

void agedFrameAndCachedTargetsBecomeUnknown()
{
    MmWaveTracker tracker({1000, 64, 64});
    auto value = event(0, 5000);
    value["frame_age_ms"] = 900;
    ingest(tracker, value, 100);
    CHECK(first(tracker, 199).at("quality") == "fresh");
    CHECK(first(tracker, 200).at("quality") == "stale_frame");
    CHECK(first(tracker, 200).at("effective_frame_age_ms") == 1000);
    CHECK(first(tracker, 200).at("observation") == "unknown");
    CHECK(first(tracker, 200).at("last_event").at("targets").size() == 1);
}

void staleFrameOnArrival()
{
    MmWaveTracker tracker;
    auto value = event(0, 9000);
    value["frame_age_ms"] = 3000;
    CHECK(ingest(tracker, value).at("accepted") == true);
    CHECK(first(tracker).at("quality") == "stale_frame");
    CHECK(first(tracker).at("observation") == "unknown");
}

void unhealthyThenSilentPriority()
{
    for (const auto& status : {"error", "disconnected"}) {
        MmWaveTracker tracker;
        auto value = event();
        value["sensor_status"] = status;
        value["frame_age_ms"] = nullptr;
        value["target_count"] = 0;
        value["targets"] = json::array();
        ingest(tracker, value, 100);
        CHECK(first(tracker).at("quality") == (std::string(status) == "error" ? "sensor_error" : "disconnected"));
        CHECK(first(tracker).at("observation") == "unknown");
        CHECK(first(tracker).at("effective_frame_age_ms").is_null());
        CHECK(first(tracker, 3100).at("quality") == "silent");
    }
}

void overflowSafeAgeAndBackwardsSnapshot()
{
    const auto maximum = std::numeric_limits<std::uint64_t>::max();
    MmWaveTracker tracker({maximum, 64, 64});
    auto value = event(0, 100);
    value["frame_age_ms"] = 100;
    ingest(tracker, value, 10);
    CHECK(first(tracker, 9).at("receiver_age_ms") == 0);
    CHECK(first(tracker, maximum - 1).at("effective_frame_age_ms") == maximum);
    CHECK(first(tracker, maximum - 1).at("quality") == "stale_frame");
}

void sequenceCacheIsBounded()
{
    MmWaveTracker tracker;
    for (std::uint32_t seq = 0; seq <= 1024; ++seq) {
        ingest(tracker, event(seq, seq));
    }
    CHECK(first(tracker).at("recent_sequence_count") == 1024);
    CHECK(ingest(tracker, event(0, 0)).at("reason") == "out_of_order");
    CHECK(ingest(tracker, event(0, 0)).at("reason") == "duplicate");
    CHECK(first(tracker).at("recent_sequence_count") == 1024);
}

void lastAcceptedIsAlwaysRecognizedAsDuplicate()
{
    MmWaveTracker tracker;
    ingest(tracker, event(5000, 5000));
    for (std::uint32_t seq = 0; seq <= 1024; ++seq) {
        CHECK(ingest(tracker, event(seq, seq)).at("reason") == "out_of_order");
    }
    CHECK(ingest(tracker, event(5000, 5000)).at("reason") == "duplicate");
}

void sequenceWrapNeedsNewSession()
{
    MmWaveTracker tracker;
    ingest(tracker, event(std::numeric_limits<std::uint32_t>::max(), 10000));
    CHECK(ingest(tracker, event(0, 10001)).at("reason") == "out_of_order");
    CHECK(ingest(tracker, event(0, 0, "session-b")).at("accepted") == true);
}

void rejectsInvalidConfig()
{
    for (const auto& config : {MmWaveTrackerConfig{0, 1, 1},
                              MmWaveTrackerConfig{1, 0, 1},
                              MmWaveTrackerConfig{1, 1, 0}}) {
        bool threw = false;
        try {
            MmWaveTracker tracker(config);
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        CHECK(threw);
    }
}

}

int main()
{
    const std::vector<std::pair<std::string, std::function<void()>>> tests = {
        {"initial state", initialState},
        {"source/receiver timestamp separation", preservesSourceAndReceiverTimes},
        {"no initial sequence loss claim", firstHighSequenceDoesNotClaimLoss},
        {"duplicate cannot refresh or replace", duplicateDoesNotRefreshOrReplace},
        {"late then duplicate", lateThenRepeatedLateIsDuplicate},
        {"holes are observed not proven lost", observedHolesAreNotGuaranteedLoss},
        {"uptime regression and equal uptime", uptimeRegressionRejectedAndEqualAllowed},
        {"new session retires old", sessionRestartRetiresOldSession},
        {"retired session limit fails closed", retiredSessionLimitIsFailClosed},
        {"origin and sensor isolation", separatesOriginsAndSensors},
        {"stream cap retains existing stream", streamLimitDoesNotEvictExisting},
        {"receiver timeout exact boundary", receiverTimeoutBoundary},
        {"empty is only no target detected", emptyFrameIsOnlyNoTargetDetected},
        {"frame freshness and cached targets", agedFrameAndCachedTargetsBecomeUnknown},
        {"stale frame on arrival", staleFrameOnArrival},
        {"error/disconnected and silence", unhealthyThenSilentPriority},
        {"overflow-safe age", overflowSafeAgeAndBackwardsSnapshot},
        {"bounded sequence memory", sequenceCacheIsBounded},
        {"known latest sequence remains duplicate", lastAcceptedIsAlwaysRecognizedAsDuplicate},
        {"sequence wrap requires session restart", sequenceWrapNeedsNewSession},
        {"invalid config", rejectsInvalidConfig},
    };
    unsigned failures = 0;
    for (const auto& test : tests) {
        try {
            test.second();
            std::cout << "PASS " << test.first << '\n';
        } catch (const std::exception& error) {
            ++failures;
            std::cerr << "FAIL " << test.first << ": " << error.what() << '\n';
        }
    }
    std::cout << "Tracker tests: " << tests.size() - failures << '/' << tests.size()
              << " passed\n";
    return failures == 0 ? 0 : 1;
}
