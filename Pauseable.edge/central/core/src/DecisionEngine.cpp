
#include "DecisionEngine.hpp"

namespace pauseable {

Decision DecisionEngine::evaluate(const MmWaveEvent& event) const
{

    if (event.velocity >= 1.0) {
        return {
            DecisionType::WanderingSuspected,
            RiskLevel::Caution,
            "빠른 움직임이 감지되었습니다.",
            "",
            "mmwave-direct",
            "",
            std::nullopt
        };
    }

    return {
        DecisionType::Normal,
        RiskLevel::Normal,
        "정상 상태입니다.",
        "",
        "mmwave-direct",
        "",
        std::nullopt
    };
}

}
