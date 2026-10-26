#pragma once


#include "Decision.hpp"
#include "MmWaveEvent.hpp"

namespace pauseable {

class DecisionEngine {
public:
    Decision evaluate(const MmWaveEvent& event) const;
};

}
