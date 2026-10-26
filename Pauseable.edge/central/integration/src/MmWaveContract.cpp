#include "MmWaveContract.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <initializer_list>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

namespace pauseable {
namespace {

using Json = nlohmann::json;
constexpr std::int64_t kSafeInteger = 9007199254740991LL;
constexpr std::int64_t kUint32Max = 4294967295LL;
constexpr std::int64_t kInt32Min = -2147483648LL;
constexpr int kMaxJsonDepth = 16;

[[noreturn]] void fail(const std::string& path, const char* message) {
    throw std::invalid_argument(path + ": " + message);
}

void object(const Json& value, std::initializer_list<const char*> keys,
            const std::string& path) {
    if (!value.is_object()) fail(path, "expected object");
    for (const auto* key : keys) {
        if (!value.contains(key)) fail(path + "." + key, "missing field");
    }

    if (value.size() != keys.size()) fail(path, "unexpected field");
}

const std::string& string(const Json& value, const std::string& path) {
    if (!value.is_string()) fail(path, "expected string");
    return value.get_ref<const std::string&>();
}

void choice(const Json& value, std::initializer_list<const char*> allowed,
            const std::string& path) {
    const auto& text = string(value, path);
    if (std::none_of(allowed.begin(), allowed.end(),
                     [&](const char* item) { return text == item; })) {
        fail(path, "unsupported value");
    }
}

std::int64_t integer(const Json& value, std::int64_t minimum,
                     std::int64_t maximum, const std::string& path) {


    if (!value.is_number_integer()) fail(path, "expected lexical integer");
    if (value.is_number_unsigned()) {
        const auto number = value.get<std::uint64_t>();
        if (number > static_cast<std::uint64_t>(maximum)) {
            fail(path, "integer outside allowed range");
        }
        return static_cast<std::int64_t>(number);
    }
    const auto number = value.get<std::int64_t>();
    if (number < minimum || number > maximum) {
        fail(path, "integer outside allowed range");
    }
    return number;
}

void number(const Json& value, const std::string& path) {
    if (!value.is_number() || !std::isfinite(value.get<double>())) {
        fail(path, "expected finite number");
    }
}

void identifier(const Json& value, std::size_t limit, const std::string& path) {
    const auto& text = string(value, path);
    const auto alnum = [](char c) {
        return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
    };
    if (text.empty() || text.size() > limit || !alnum(text.front())) {
        fail(path, "invalid identifier");
    }
    for (const auto c : text) {
        if (!alnum(c) && c != '_' && c != '-') fail(path, "invalid identifier");
    }
}

void stringLength(const Json& value, std::size_t minimum,
                  std::size_t maximum, const std::string& path) {
    const auto& text = string(value, path);


    const auto length = static_cast<std::size_t>(std::count_if(
        text.begin(), text.end(), [](unsigned char c) { return (c & 0xC0) != 0x80; }));
    if (length < minimum || length > maximum) fail(path, "invalid string length");
}

void timestamp(const Json& value, const std::string& path) {
    if (value.is_null()) return;
    const auto& text = string(value, path);

    if (!(text.size() == 20 || (text.size() >= 22 && text.size() <= 27)) ||
        text[4] != '-' || text[7] != '-' || text[10] != 'T' ||
        text[13] != ':' || text[16] != ':' || text.back() != 'Z') {
        fail(path, "expected UTC timestamp ending in Z");
    }
    for (std::size_t i = 0; i + 1 < text.size(); ++i) {
        if (i == 4 || i == 7 || i == 10 || i == 13 || i == 16) continue;
        if (i == 19 && text.size() > 20) {
            if (text[i] != '.') fail(path, "invalid timestamp fraction");
        } else if (text[i] < '0' || text[i] > '9') {
            fail(path, "invalid timestamp digit");
        }
    }
    const auto digits = [&](std::size_t offset, std::size_t count) {
        int result = 0;
        for (std::size_t i = offset; i < offset + count; ++i) {
            result = result * 10 + text[i] - '0';
        }
        return result;
    };
    const int year = digits(0, 4), month = digits(5, 2), day = digits(8, 2);
    const int hour = digits(11, 2), minute = digits(14, 2), second = digits(17, 2);
    if (year == 0 || month < 1 || month > 12 || day < 1 ||
        hour > 23 || minute > 59 || second > 59) {
        fail(path, "invalid calendar date/time");
    }
    constexpr int days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    const bool leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    const int limit = days[month - 1] + (month == 2 && leap ? 1 : 0);
    if (day > limit) fail(path, "invalid calendar date/time");
}

void validate(const Json& event) {
    object(event, {"schema_version", "event_id", "source", "data_origin",
                   "sensor_id", "session_id", "seq", "occurred_at", "time_status",
                   "uptime_ms", "measurement_profile", "sensor_status",
                   "frame_age_ms", "target_count", "targets_truncated", "targets",
                   "replay"}, "$");
    choice(event.at("schema_version"), {"1.0"}, "$.schema_version");
    stringLength(event.at("event_id"), 5, 108, "$.event_id");
    choice(event.at("source"), {"esp32-ld6004", "pauseable-simulator", "pauseable-replay"},
           "$.source");
    choice(event.at("data_origin"), {"live", "simulated", "replay"}, "$.data_origin");
    identifier(event.at("sensor_id"), 48, "$.sensor_id");
    identifier(event.at("session_id"), 48, "$.session_id");
    const auto seq = integer(event.at("seq"), 0, kUint32Max, "$.seq");
    timestamp(event.at("occurred_at"), "$.occurred_at");
    choice(event.at("time_status"), {"synced", "unsynced"}, "$.time_status");
    const auto uptime = integer(event.at("uptime_ms"), 0, kSafeInteger, "$.uptime_ms");
    choice(event.at("measurement_profile"), {"ld6004-target-raw-v1"},
           "$.measurement_profile");
    choice(event.at("sensor_status"), {"ok", "disconnected", "error"}, "$.sensor_status");
    if (!event.at("frame_age_ms").is_null()) {
        integer(event.at("frame_age_ms"), 0, kSafeInteger, "$.frame_age_ms");
    }
    const auto count = integer(event.at("target_count"), 0, 4, "$.target_count");
    if (!event.at("targets_truncated").is_boolean()) {
        fail("$.targets_truncated", "expected boolean");
    }
    const bool truncated = event.at("targets_truncated").get<bool>();
    const auto& targets = event.at("targets");
    if (!targets.is_array() || targets.size() > 4) {
        fail("$.targets", "expected array with at most four targets");
    }
    std::set<std::int64_t> ids;
    for (std::size_t i = 0; i < targets.size(); ++i) {
        const auto path = "$.targets[" + std::to_string(i) + "]";
        const auto& target = targets.at(i);
        object(target, {"id", "x", "y", "z", "doppler"}, path);
        const auto id = integer(target.at("id"), kInt32Min, kUint32Max, path + ".id");
        number(target.at("x"), path + ".x");
        number(target.at("y"), path + ".y");
        number(target.at("z"), path + ".z");
        integer(target.at("doppler"), kInt32Min, kUint32Max, path + ".doppler");
        if (!ids.insert(id).second) fail("$.targets", "duplicate target id");
    }
    const auto& replay = event.at("replay");
    if (!replay.is_null()) {
        object(replay, {"log_id", "frame_index", "original_origin",
                       "original_event_id", "original_occurred_at"}, "$.replay");
        identifier(replay.at("log_id"), 64, "$.replay.log_id");
        integer(replay.at("frame_index"), 0, kSafeInteger, "$.replay.frame_index");
        choice(replay.at("original_origin"), {"live", "simulated", "unknown"},
               "$.replay.original_origin");
        if (!replay.at("original_event_id").is_null()) {
            stringLength(replay.at("original_event_id"), 1, 108,
                         "$.replay.original_event_id");
        }
        timestamp(replay.at("original_occurred_at"), "$.replay.original_occurred_at");
    }

    const auto& origin = event.at("data_origin").get_ref<const std::string&>();
    const char* expectedSource = origin == "live" ? "esp32-ld6004" :
                                 origin == "simulated" ? "pauseable-simulator" : "pauseable-replay";
    if (event.at("source") != expectedSource) fail("$.source", "does not match data_origin");
    const auto expectedId = event.at("sensor_id").get<std::string>() + ":" +
                            event.at("session_id").get<std::string>() + ":" +
                            std::to_string(seq);
    if (event.at("event_id") != expectedId) {
        fail("$.event_id", "must equal sensor_id:session_id:seq");
    }
    if ((event.at("time_status") == "synced") == event.at("occurred_at").is_null()) {
        fail("$.occurred_at", "synced needs UTC timestamp; unsynced needs null");
    }
    if (static_cast<std::size_t>(count) != targets.size()) {
        fail("$.target_count", "does not equal targets length");
    }
    if (truncated && count != 4) fail("$.targets_truncated", "requires four targets");
    if (event.at("sensor_status") != "ok") {
        if (count != 0 || !targets.empty() || truncated) {
            fail("$.sensor_status", "unhealthy sensor must carry no targets");
        }
        if (!event.at("frame_age_ms").is_null()) {
            fail("$.frame_age_ms", "unhealthy sensor needs null");
        }
    } else {
        if (event.at("frame_age_ms").is_null()) fail("$.frame_age_ms", "ok sensor needs age");
        if (event.at("frame_age_ms").get<std::int64_t>() > uptime) {
            fail("$.frame_age_ms", "cannot exceed sender session uptime");
        }
    }
    if (origin == "replay") {
        if (replay.is_null()) fail("$.replay", "provenance required for replay");
        if (replay.at("original_event_id") == event.at("event_id")) {
            fail("$.replay.original_event_id", "replay needs a new event identity");
        }
    } else if (!replay.is_null()) {
        fail("$.replay", "must be null outside replay mode");
    }
}

}

nlohmann::json parseMmWavePacket(const std::string& payload) {
    if (payload.size() > kMmWaveMaxPacketBytes) fail("$", "packet exceeds 4096 bytes");


    if (payload.find('\0') != std::string::npos) fail("$", "raw NUL byte is not JSON");
    if (payload.size() >= 3 && payload.compare(0, 3, "\xEF\xBB\xBF") == 0) {
        fail("$", "UTF-8 BOM is not allowed");
    }
    std::vector<std::unordered_set<std::string>> objectKeys;
    const auto callback = [&](int depth, Json::parse_event_t event, Json& parsed) {
        if (depth > kMaxJsonDepth) fail("$", "JSON nesting exceeds security limit");
        if (event == Json::parse_event_t::object_start) {
            objectKeys.emplace_back();
        } else if (event == Json::parse_event_t::key) {
            if (objectKeys.empty() ||
                !objectKeys.back().insert(parsed.get<std::string>()).second) {
                fail("$", "duplicate JSON key");
            }
        } else if (event == Json::parse_event_t::object_end) {
            if (!objectKeys.empty()) objectKeys.pop_back();
        }
        return true;
    };
    try {
        auto event = Json::parse(payload, callback, true, false);
        validate(event);
        return event;
    } catch (const Json::exception&) {

        fail("$", "invalid JSON encoding, syntax, or numeric range");
    }
}

}
