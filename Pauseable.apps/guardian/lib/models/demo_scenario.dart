enum DemoScenario {
  normal,
  repetitiveBehavior,
  inactivity,
  nightMovement,
  doorExit;

  String get id => switch (this) {
    DemoScenario.normal => 'normal',
    DemoScenario.repetitiveBehavior => 'repetitive_behavior',
    DemoScenario.inactivity => 'inactivity',
    DemoScenario.nightMovement => 'night_movement',
    DemoScenario.doorExit => 'door_exit',
  };

  String get label => switch (this) {
    DemoScenario.normal => '정상 상태',
    DemoScenario.repetitiveBehavior => '현관문 반복 행동',
    DemoScenario.inactivity => '장시간 무활동',
    DemoScenario.nightMovement => '야간 움직임',
    DemoScenario.doorExit => '외출 장면 촬영',
  };

  String get description => switch (this) {
    DemoScenario.normal => '특이사항 없이 일상생활 중인 상태',
    DemoScenario.repetitiveBehavior => '20분 동안 현관문을 7회 여닫은 상황',
    DemoScenario.inactivity => '거실에서 2시간 동안 움직임이 없는 상황',
    DemoScenario.nightMovement => '새벽 시간에 침실에서 거실로 이동한 상황',
    DemoScenario.doorExit => '현관 카메라에 외출 장면이 촬영된 상황',
  };

  static DemoScenario fromJson(String value) {
    return DemoScenario.values.firstWhere(
      (scenario) => scenario.id == value,
      orElse: () => DemoScenario.repetitiveBehavior,
    );
  }
}
