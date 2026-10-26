class PatientStatus {
  const PatientStatus({
    required this.id,
    required this.name,
    required this.location,
    required this.activity,
    required this.isDeviceConnected,
    required this.lastConnectedLabel,
    required this.safetyLabel,
    required this.daySummary,
  });

  final String id;
  final String name;
  final String location;
  final String activity;
  final bool isDeviceConnected;
  final String lastConnectedLabel;
  final String safetyLabel;
  final String daySummary;

  factory PatientStatus.fromJson(Map<String, dynamic> json) {
    return PatientStatus(
      id: json['id'] as String,
      name: json['name'] as String,
      location: json['location'] as String,
      activity: json['activity'] as String,
      isDeviceConnected: json['is_device_connected'] as bool,
      lastConnectedLabel: json['last_connected_label'] as String,
      safetyLabel: json['safety_label'] as String,
      daySummary: json['day_summary'] as String,
    );
  }
}
