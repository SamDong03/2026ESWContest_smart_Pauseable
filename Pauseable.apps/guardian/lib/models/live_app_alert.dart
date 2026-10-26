import 'guardian_alert.dart';

class LiveAppAlert {
  const LiveAppAlert({
    required this.id,
    required this.occurredAt,
    required this.riskLevel,
    required this.alertType,
    required this.title,
    required this.message,
    this.deviceId,
    this.relatedEventId,
    this.isRead = false,
  });

  final String id;
  final DateTime occurredAt;
  final String riskLevel;
  final String alertType;
  final String title;
  final String message;
  final String? deviceId;
  final String? relatedEventId;
  final bool isRead;

  factory LiveAppAlert.fromJson(Map<String, dynamic> json) {
    return LiveAppAlert(
      id: json['alert_id'] as String,
      occurredAt: DateTime.parse(json['occurred_at'] as String),
      riskLevel: json['risk_level'] as String,
      alertType: json['alert_type'] as String? ?? 'appliance',
      title: json['title'] as String,
      message: json['message'] as String,
      deviceId: json['device_id'] as String?,
      relatedEventId: json['related_event_id'] as String?,
      isRead: json['is_read'] as bool? ?? false,
    );
  }

  LiveAppAlert copyWith({bool? isRead}) => LiveAppAlert(
    id: id,
    occurredAt: occurredAt,
    riskLevel: riskLevel,
    alertType: alertType,
    title: title,
    message: message,
    deviceId: deviceId,
    relatedEventId: relatedEventId,
    isRead: isRead ?? this.isRead,
  );

  GuardianAlert toGuardianAlert() {
    return GuardianAlert(
      id: id,
      type: switch (alertType) {
        'repetitive_behavior' => GuardianAlertType.repetitiveBehavior,
        'wandering' => GuardianAlertType.wandering,
        'inactivity' => GuardianAlertType.inactivity,
        'medication' => GuardianAlertType.medication,
        'night_movement' => GuardianAlertType.nightMovement,
        'door_event' => GuardianAlertType.doorEvent,
        _ => GuardianAlertType.appliance,
      },
      category: riskLevel == 'normal' ? '상태 변경' : '확인 필요',
      title: title,
      description: message,
      timeLabel: _timeLabel(occurredAt),
      deviceId: deviceId,
      relatedEventId: relatedEventId,
      isServerAlert: true,
      isRead: isRead,
    );
  }

  static String _timeLabel(DateTime value) {
    final local = value.toLocal();
    String two(int number) => number.toString().padLeft(2, '0');
    return '${local.month}월 ${local.day}일 ${two(local.hour)}:${two(local.minute)}:${two(local.second)}';
  }
}
