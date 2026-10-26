#pragma once


#include <cstdint>

namespace pauseable {

struct MmWaveEvent {
    std::int64_t timestampMs{0};

    double x{0.0};
    double y{0.0};
    double velocity{0.0};
};

}
