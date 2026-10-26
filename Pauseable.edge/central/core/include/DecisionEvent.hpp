#pragma once

#include <string>

#include "ActionRouter.hpp"
#include "BehaviorInference.hpp"

namespace pauseable {

std::string makeDecisionEventPayload(
    const BehaviorInference& inference,
    const ActionPlan& plan);

}
