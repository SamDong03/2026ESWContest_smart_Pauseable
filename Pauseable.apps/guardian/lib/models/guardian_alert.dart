enum GuardianAlertType {
  repetitiveBehavior,
  wandering,
  inactivity,
  medication,
  nightMovement,
  appliance,
  doorEvent,
}

class GuardianAlert {
  const GuardianAlert({
    required this.id,
    required this.type,
    required this.category,
    required this.title,
    required this.description,
    required this.timeLabel,
    this.deviceId,
    this.relatedEventId,
    this.currentCount,
    this.normalMin,
    this.normalMax,
    this.isServerAlert = false,
    this.isRead = true,
  });

  final String id;
  final GuardianAlertType type;
  final String category;
  final String title;
  final String description;
  final String timeLabel;
  final String? deviceId;
  final String? relatedEventId;
  final int? currentCount;
  final int? normalMin;
  final int? normalMax;
  final bool isServerAlert;
  final bool isRead;

  bool get isRepetitiveBehavior => type == GuardianAlertType.repetitiveBehavior;

  factory GuardianAlert.fromJson(Map<String, dynamic> json) {
    return GuardianAlert(
      id: json['id'] as String,
      type: _guardianAlertTypeFromJson(json['type'] as String),
      category: json['category'] as String,
      title: json['title'] as String,
      description: json['description'] as String,
      timeLabel: json['time_label'] as String,
      deviceId: json['device_id'] as String?,
      relatedEventId: json['related_event_id'] as String?,
      currentCount: json['current_count'] as int?,
      normalMin: json['normal_min'] as int?,
      normalMax: json['normal_max'] as int?,
    );
  }
}

GuardianAlertType _guardianAlertTypeFromJson(String value) {
  return switch (value) {
    'repetitive_behavior' => GuardianAlertType.repetitiveBehavior,
    'wandering' => GuardianAlertType.wandering,
    'inactivity' => GuardianAlertType.inactivity,
    'medication' => GuardianAlertType.medication,
    'night_movement' => GuardianAlertType.nightMovement,
    'appliance' => GuardianAlertType.appliance,
    'door_event' => GuardianAlertType.doorEvent,
    _ => throw FormatException('Unknown guardian alert type: $value'),
  };
}
