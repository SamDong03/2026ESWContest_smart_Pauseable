#include "MmWaveContract.hpp"

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

using Json = nlohmann::json;
std::size_t checks = 0;

Json fixture() {
    return Json::parse(R"json({
      "schema_version":"1.0", "event_id":"test-radar:example-session:1",
      "source":"pauseable-simulator", "data_origin":"simulated",
      "sensor_id":"test-radar", "session_id":"example-session", "seq":1,
      "occurred_at":"2026-09-08T03:00:00Z", "time_status":"synced",
      "uptime_ms":100, "measurement_profile":"ld6004-target-raw-v1",
      "sensor_status":"ok", "frame_age_ms":0, "target_count":1,
      "targets_truncated":false,
      "targets":[{"id":1,"x":-1.2,"y":0.5,"z":1.3,"doppler":-1}],
      "replay":null
    })json");
}

Json replayFixture() {
    auto event = fixture();
    event["source"] = "pauseable-replay";
    event["data_origin"] = "replay";
    event["replay"] = {
        {"log_id", "test-log"}, {"frame_index", 0},
        {"original_origin", "simulated"}, {"original_event_id", "old:event:1"},
        {"original_occurred_at", "2024-02-29T23:59:59.123456Z"}};
    return event;
}

void accepted(const Json& value) {
    ++checks;
    if (pauseable::parseMmWavePacket(value.dump()) != value) {
        throw std::runtime_error("accepted packet was not preserved");
    }
}

void rejectedWire(const std::string& payload, const std::string& label) {
    ++checks;
    try {
        pauseable::parseMmWavePacket(payload);
    } catch (const std::invalid_argument&) {
        return;
    }
    throw std::runtime_error("invalid packet accepted: " + label);
}

void rejected(const Json& value, const std::string& label) {
    rejectedWire(value.dump(), label);
}

std::string replaced(std::string text, const std::string& find,
                     const std::string& replacement) {
    const auto at = text.find(find);
    if (at == std::string::npos) throw std::runtime_error("bad test replacement");
    text.replace(at, find.size(), replacement);
    return text;
}

void runTests() {
    accepted(fixture());
    accepted(replayFixture());
    auto event = fixture();
    event["source"] = "esp32-ld6004";
    event["data_origin"] = "live";
    event["time_status"] = "unsynced";
    event["occurred_at"] = nullptr;
    accepted(event);

    for (const char* state : {"ok", "disconnected", "error"}) {
        event = fixture();
        event["sensor_status"] = state;
        event["target_count"] = 0;
        event["targets"] = Json::array();
        if (std::string(state) != "ok") event["frame_age_ms"] = nullptr;
        accepted(event);
    }

    for (const auto seq : {0LL, 4294967295LL}) {
        event = fixture();
        const std::string sensor(48, 'a'), session(48, 'b');
        event["sensor_id"] = sensor;
        event["session_id"] = session;
        event["seq"] = seq;
        event["event_id"] = sensor + ":" + session + ":" + std::to_string(seq);
        event["uptime_ms"] = 9007199254740991LL;
        event["frame_age_ms"] = 9007199254740991LL;
        event["targets"][0]["id"] = 4294967295LL;
        event["targets"][0]["doppler"] = -2147483648LL;
        accepted(event);
    }

    const auto base = fixture();
    for (auto it = base.begin(); it != base.end(); ++it) {
        event = base;
        event.erase(it.key());
        rejected(event, "missing " + it.key());
    }
    for (const char* field : {"seq", "uptime_ms", "frame_age_ms", "target_count"}) {
        for (const auto& invalid : {Json(true), Json(false), Json("1"), Json(1.0)}) {
            event = fixture();
            event[field] = invalid;
            rejected(event, std::string("integer type ") + field);
        }
    }
    for (const char* field : {"id", "x", "y", "z", "doppler"}) {
        event = fixture();
        event["targets"][0][field] = true;
        rejected(event, std::string("boolean numeric ") + field);
    }
    for (const char* field : {"id", "doppler"}) {
        for (const auto& invalid : {Json(-2147483649LL), Json(4294967296LL), Json(1.0)}) {
            event = fixture();
            event["targets"][0][field] = invalid;
            rejected(event, std::string("target integer ") + field);
        }
    }
    for (const auto value : {-1LL, 4294967296LL}) {
        event = fixture();
        event["seq"] = value;
        rejected(event, "seq range");
    }
    for (const char* field : {"uptime_ms", "frame_age_ms"}) {
        for (const auto value : {-1LL, 9007199254740992LL}) {
            event = fixture();
            event[field] = value;
            rejected(event, "safe integer range");
        }
    }
    for (const char* field : {"sensor_id", "session_id"}) {
        for (const std::string invalid : {"", "../sensor", "has space", "UPPER", "id\n"}) {
            event = fixture();
            event[field] = invalid;
            rejected(event, "identifier");
        }
        event = fixture();
        event[field] = std::string(49, 'a');
        rejected(event, "long identifier");
    }

    for (const char* valid : {"0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z",
                              "2000-02-29T01:02:03Z", "2024-02-29T23:59:59.1Z",
                              "2026-09-08T00:00:00.123456Z"}) {
        event = fixture();
        event["occurred_at"] = valid;
        accepted(event);
    }
    for (const char* invalid : {"", "0000-01-01T00:00:00Z", "1900-02-29T00:00:00Z",
            "2026-02-29T00:00:00Z", "2026-09-31T00:00:00Z", "2026-00-01T00:00:00Z",
            "2026-13-01T00:00:00Z", "2026-01-00T00:00:00Z", "2026-01-01T24:00:00Z",
            "2026-01-01T00:60:00Z", "2026-01-01T00:00:60Z", "2026-01-01 00:00:00Z",
            "2026-01-01T00:00:00z", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00",
            "2026-01-01T00:00:00.Z", "2026-01-01T00:00:00.1234567Z"}) {
        event = fixture();
        event["occurred_at"] = invalid;
        rejected(event, "invalid timestamp");
    }
    event = fixture();
    event["time_status"] = "unsynced";
    rejected(event, "unsynced timestamp");
    event = fixture();
    event["occurred_at"] = nullptr;
    rejected(event, "synced null timestamp");
    event = fixture();
    event["source"] = "esp32-ld6004";
    rejected(event, "mismatched source");
    event = fixture();
    event["event_id"] = "test-radar:example-session:01";
    rejected(event, "noncanonical identity");

    event = fixture();
    event["target_count"] = 0;
    rejected(event, "count mismatch");
    event = fixture();
    event["targets"].push_back(event["targets"][0]);
    event["target_count"] = 2;
    rejected(event, "duplicate target");
    event = fixture();
    event["targets_truncated"] = true;
    rejected(event, "incorrect truncation");
    for (int id = 2; id <= 4; ++id) {
        auto target = event["targets"][0];
        target["id"] = id;
        event["targets"].push_back(target);
    }
    event["target_count"] = 4;
    accepted(event);
    event["targets"].push_back(event["targets"][0]);
    rejected(event, "five targets");
    for (const char* state : {"error", "disconnected"}) {
        event = fixture();
        event["sensor_status"] = state;
        event["frame_age_ms"] = nullptr;
        rejected(event, "unhealthy targets");
        event["target_count"] = 0;
        event["targets"] = Json::array();
        event["frame_age_ms"] = 0;
        rejected(event, "unhealthy age");
    }
    event = fixture();
    event["frame_age_ms"] = nullptr;
    rejected(event, "healthy null age");
    event["frame_age_ms"] = 101;
    rejected(event, "age beyond uptime");

    event = replayFixture();
    event["replay"]["original_origin"] = "unknown";
    event["replay"]["original_event_id"] = nullptr;
    event["replay"]["original_occurred_at"] = nullptr;
    accepted(event);
    event["replay"] = nullptr;
    rejected(event, "missing replay provenance");
    event = replayFixture();
    event["replay"]["original_event_id"] = event["event_id"];
    rejected(event, "reused replay identity");
    event = fixture();
    event["replay"] = replayFixture()["replay"];
    rejected(event, "nonreplay provenance");
    for (const char* field : {"log_id", "frame_index", "original_origin",
                              "original_event_id", "original_occurred_at"}) {
        event = replayFixture();
        event["replay"].erase(field);
        rejected(event, std::string("missing replay ") + field);
    }
    event = replayFixture();
    event["replay"]["original_origin"] = "replay";
    rejected(event, "nested provenance origin");
    event = replayFixture();
    event["replay"]["original_occurred_at"] = "2026-02-30T00:00:00Z";
    rejected(event, "original invalid date");
    event = replayFixture();
    std::string unicode;
    for (int i = 0; i < 108; ++i) unicode += "\xEA\xB0\x80";
    event["replay"]["original_event_id"] = unicode;
    accepted(event);
    event["replay"]["original_event_id"] = unicode + "a";
    rejected(event, "Unicode length");
    event = fixture();
    event["extra"] = "unknown";
    rejected(event, "root extra key");
    event = fixture();
    event["targets"][0]["extra"] = 1;
    rejected(event, "target extra key");
    event = replayFixture();
    event["replay"]["extra"] = 1;
    rejected(event, "replay extra key");

    const auto wire = fixture().dump();
    rejectedWire(replaced(wire, "\"seq\":1", "\"seq\":1,\"seq\":1"), "root duplicate");
    rejectedWire(replaced(wire, "\"seq\":1", "\"seq\":1,\"\\u0073eq\":1"), "escaped duplicate");
    rejectedWire(replaced(wire, "\"id\":1", "\"id\":1,\"id\":1"), "target duplicate");
    rejectedWire(replaced(replayFixture().dump(), "\"frame_index\":0",
                         "\"frame_index\":0,\"frame_index\":0"), "replay duplicate");
    for (const char* invalid : {"NaN", "Infinity", "-Infinity", "1e999"}) {
        rejectedWire(replaced(wire, "\"x\":-1.2", std::string("\"x\":") + invalid),
                     "nonfinite coordinate");
    }
    rejectedWire(replaced(wire, "\"seq\":1", "\"seq\":1e0"), "exponent integer");
    rejectedWire(replaced(wire, "\"seq\":1", "\"seq\":18446744073709551616"), "overflow integer");
    for (const std::string invalid : {"", "null", "[]", "true", "1", "{", "\xFF"}) {
        rejectedWire(invalid, "malformed/root type");
    }
    rejectedWire(wire + "{}", "multiple roots");
    rejectedWire(wire + std::string(1, '\0') + "garbage", "raw NUL trailing bytes");
    rejectedWire("\xEF\xBB\xBF" + wire, "UTF-8 BOM");
    rejectedWire(replaced(replayFixture().dump(), "old:event:1", "\\ud800"), "lone surrogate");
    rejectedWire(std::string(1500, '[') + std::string(1500, ']'), "deep array");
    std::string padded = wire + std::string(pauseable::kMmWaveMaxPacketBytes - wire.size(), ' ');
    ++checks;
    pauseable::parseMmWavePacket(padded);
    rejectedWire(padded + " ", "oversize whitespace");
}

}

int main(int argc, char** argv) {

    if (argc == 2 && std::string(argv[1]) == "--jsonl-oracle") {
        std::string line;
        while (std::getline(std::cin, line)) {
            try {
                pauseable::parseMmWavePacket(line);
                std::cout << "ACCEPT\n";
            } catch (const std::invalid_argument&) {
                std::cout << "REJECT\n";
            }
        }
        return 0;
    }
    try {
        runTests();
        std::cout << "MmWave contract: " << checks << " checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "MmWave contract FAIL: " << error.what() << '\n';
        return 1;
    }
}
