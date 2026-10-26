import 'package:flutter_test/flutter_test.dart';
import 'package:pauseable_guardian/models/guardian_alert.dart';
import 'package:pauseable_guardian/models/live_app_alert.dart';

void main() {
  test('REST door alert keeps its photo reference after marking it read', () {
    final alert = LiveAppAlert.fromJson({
      'alert_id': 'door-camera-001',
      'occurred_at': '2026-10-06T00:00:00Z',
      'risk_level': 'normal',
      'alert_type': 'door_event',
      'title': '현관 사진',
      'message': '새 사진을 확인해 주세요.',
      'related_event_id': 'camera-001',
    }).copyWith(isRead: true).toGuardianAlert();
    expect(alert.type, GuardianAlertType.doorEvent);
    expect(alert.relatedEventId, 'camera-001');
    expect(alert.isRead, isTrue);
    expect(alert.isServerAlert, isTrue);
  });
}
