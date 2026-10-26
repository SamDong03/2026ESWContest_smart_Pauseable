#pragma once

#include <cstddef>
#include <string>

#include <nlohmann/json.hpp>

namespace pauseable {

inline constexpr std::size_t kMmWaveMaxPacketBytes = 4096;


nlohmann::json parseMmWavePacket(const std::string& payload);

}
