
class VoiceConsentReceipt {
  const VoiceConsentReceipt({
    required this.consentId,
    required this.patientId,
    required this.policyVersion,
    required this.acceptedAt,
  });

  static const currentPolicyVersion = '2026-10-24';
  final String consentId;
  final String patientId;
  final String policyVersion;
  final DateTime acceptedAt;

  factory VoiceConsentReceipt.fromJson(Map<String, dynamic> json) {
    if (json['accepted'] != true ||
        json['scope'] != 'guardian_voice_training' ||
        json['policy_version'] != currentPolicyVersion ||
        !RegExp(r'^voice-consent-[0-9a-f]{32}$')
            .hasMatch(json['consent_id'] as String? ?? '') ||
        (json['patient_id'] as String? ?? '').isEmpty) {
      throw const FormatException('Invalid voice consent receipt');
    }
    final timestamp = json['accepted_at'] as String;
    if (!RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(timestamp)) {
      throw const FormatException('Consent timestamp requires a timezone');
    }
    return VoiceConsentReceipt(
      consentId: json['consent_id'] as String,
      patientId: json['patient_id'] as String,
      policyVersion: json['policy_version'] as String,
      acceptedAt: DateTime.parse(timestamp).toUtc(),
    );
  }
}
