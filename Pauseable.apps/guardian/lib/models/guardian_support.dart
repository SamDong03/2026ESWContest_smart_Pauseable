class GuardianProfile {
  const GuardianProfile({
    required this.name,
    required this.relationship,
    required this.phoneNumber,
    this.patientName = '',
    this.patientCallName = '',
  });

  final String name;
  final String relationship;
  final String phoneNumber;
  final String patientName;
  final String patientCallName;

  bool get hasNames => name.trim().isNotEmpty && patientName.trim().isNotEmpty;

  String get guardianLabel => _nameLabel(name, '보호자님');
  String get patientLabel => _nameLabel(patientName, '돌봄 대상자');

  static String _nameLabel(String name, String fallback) {
    final trimmed = name.trim();
    if (trimmed.isEmpty) return fallback;
    return trimmed.endsWith('님') ? trimmed : '$trimmed님';
  }

  factory GuardianProfile.fromJson(Map<String, dynamic> json) {
    return GuardianProfile(
      name: json['name'] as String,
      relationship: json['relationship'] as String,
      phoneNumber: json['phone_number'] as String,
      patientName: json['patient_name'] as String? ?? '',
      patientCallName: json['patient_call_name'] as String? ?? '',
    );
  }
}

class GuardianPreferences {
  const GuardianPreferences({
    required this.safetyNotifications,
    required this.soundEnabled,
  });

  final bool safetyNotifications;
  final bool soundEnabled;

  factory GuardianPreferences.fromJson(Map<String, dynamic> json) {
    return GuardianPreferences(
      safetyNotifications: json['safety_notifications'] as bool,
      soundEnabled: json['sound_enabled'] as bool,
    );
  }
}

class DeviceServiceStatus {
  const DeviceServiceStatus({
    required this.name,
    required this.isConnected,
    required this.detail,
  });

  final String name;
  final bool isConnected;
  final String detail;

  factory DeviceServiceStatus.fromJson(Map<String, dynamic> json) {
    return DeviceServiceStatus(
      name: json['name'] as String,
      isConnected: json['is_connected'] as bool,
      detail: json['detail'] as String,
    );
  }
}

class DeviceConnectionStatus {
  const DeviceConnectionStatus({
    required this.deviceName,
    required this.isOnline,
    required this.lastCheckedLabel,
    required this.services,
  });

  final String deviceName;
  final bool isOnline;
  final String lastCheckedLabel;
  final List<DeviceServiceStatus> services;

  factory DeviceConnectionStatus.fromJson(Map<String, dynamic> json) {
    return DeviceConnectionStatus(
      deviceName: json['device_name'] as String,
      isOnline: json['is_online'] as bool,
      lastCheckedLabel: json['last_checked_label'] as String,
      services: List.unmodifiable(
        (json['services'] as List<dynamic>).map(
          (service) =>
              DeviceServiceStatus.fromJson(service as Map<String, dynamic>),
        ),
      ),
    );
  }
}

class GuardianActionResult {
  const GuardianActionResult({
    required this.title,
    required this.message,
    required this.referenceId,
  });

  final String title;
  final String message;
  final String referenceId;

  factory GuardianActionResult.fromJson(Map<String, dynamic> json) {
    return GuardianActionResult(
      title: json['title'] as String,
      message: json['message'] as String,
      referenceId: json['reference_id'] as String,
    );
  }
}
