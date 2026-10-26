import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pauseable_guardian/models/activity_summary.dart';
import 'package:pauseable_guardian/models/demo_scenario.dart';
import 'package:pauseable_guardian/models/guardian_alert.dart';
import 'package:pauseable_guardian/models/guardian_support.dart';
import 'package:pauseable_guardian/models/live_app_alert.dart';
import 'package:pauseable_guardian/models/voice_training_prompt.dart';
import 'package:pauseable_guardian/repositories/mock_guardian_repository.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('old and new care profiles keep the optional spoken name separate', () {
    final legacy = {
      'name': '이보호',
      'patient_name': '박돌봄',
      'relationship': '딸',
      'phone_number': '',
    };
    expect(GuardianProfile.fromJson(legacy).patientCallName, isEmpty);
    final profile = GuardianProfile.fromJson({
      ...legacy,
      'patient_call_name': '엄마',
    });
    expect(profile.patientCallName, '엄마');
    expect(profile.patientLabel, '박돌봄님');
    expect(profile.relationship, '딸');
  });

  test('mock JSON is converted to guardian domain models', () async {
    final snapshot = await MockGuardianRepository().loadSnapshot();

    expect(snapshot.patient.name, '김영희');
    expect(snapshot.patient.id, 'byunwoojin');
    expect(snapshot.patient.isDeviceConnected, isTrue);
    expect(snapshot.alerts, hasLength(2));
    expect(
      snapshot.alerts.map((alert) => alert.title),
      isNot(contains('저녁 복약 시간 예정')),
    );
    expect(
      snapshot.repetitiveBehaviorAlert.type,
      GuardianAlertType.repetitiveBehavior,
    );
    expect(snapshot.repetitiveBehaviorAlert.currentCount, 7);
    expect(snapshot.activity.events, hasLength(6));
    expect(snapshot.activity.events.first.type, ActivityEventType.light);
    expect(snapshot.activity.events.first.timeLabel, '오전 7:30:12');
    expect(snapshot.activity.events[2].title, '냉장고 문 닫힘');
    expect(snapshot.activity.events[2].state, ActivityEventState.closed);
    expect(snapshot.activity.events[2].occurredAt.second, 19);
    expect(snapshot.activity.events.last.title, '현관문 닫힘');
    expect(snapshot.activity.events.last.timeLabel, '오후 2:42:17');
    expect(snapshot.demoScenario, DemoScenario.repetitiveBehavior);
  });

  test('recording script preserves 160 distinct fixed prompts', () async {
    final source = await rootBundle.loadString(
      'assets/data/voice_training_script.json',
    );
    final script = VoiceTrainingScript.fromJson(
      jsonDecode(source) as Map<String, dynamic>,
    );

    expect(script.targetSeconds, 800);
    expect(script.totalPrompts, 160);
    expect(script.prompts, hasLength(160));
    expect(script.prompts.first.fileName, 'S001.wav');
    expect(script.prompts.first.text, '할머니 맑은 아침 햇살이 창문 사이로 들어와요.');
    expect(script.prompts[159].fileName, 'S160.wav');
    expect(script.prompts[159].category, '호칭과 억양');
    expect(script.prompts.last.fileName, 'S160.wav');
    expect(
      script.prompts.map((prompt) => prompt.fileName).toSet(),
      hasLength(160),
    );
    expect(script.promptForClipCount(159)?.fileName, 'S160.wav');
    expect(script.promptForClipCount(160), isNull);
  });

  test('live server alert is converted into the guardian alert list', () {
    final liveAlert = LiveAppAlert.fromJson({
      'alert_id': 'ha-event-001',
      'occurred_at': '2026-09-21T11:11:37Z',
      'risk_level': 'caution',
      'alert_type': 'repetitive_behavior',
      'device_id': 'binary_sensor.front_door',
      'title': '현관문 반복 행동 감지',
      'message': '20분 동안 현관문이 7회 열리고 닫혔어요.',
    });

    final alert = liveAlert.toGuardianAlert();
    expect(alert.id, 'ha-event-001');
    expect(alert.type, GuardianAlertType.repetitiveBehavior);
    expect(alert.category, '확인 필요');
    expect(alert.deviceId, 'binary_sensor.front_door');
    expect(alert.isServerAlert, isTrue);
    expect(alert.isRead, isFalse);
    expect(alert.timeLabel, endsWith(':37'));
  });

  test('wandering decision appears as a distinct guardian safety alert', () {
    final alert = LiveAppAlert.fromJson({
      'alert_id': 'evt-wandering-001',
      'occurred_at': '2026-10-05T10:11:37Z',
      'risk_level': 'danger',
      'alert_type': 'wandering',
      'device_id': 'pi5-home-01',
      'title': '배회 의심 감지',
      'message': '이동 패턴에 변화가 감지되었습니다. 상황을 확인해 주세요.',
    }).toGuardianAlert();

    expect(alert.type, GuardianAlertType.wandering);
    expect(alert.category, '확인 필요');
    expect(alert.isServerAlert, isTrue);
    expect(alert.title, '배회 의심 감지');
  });
}
