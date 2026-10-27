import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../config/api_config.dart';
import '../models/guardian_snapshot.dart';
import '../models/guardian_support.dart';
import '../models/voice_training_progress.dart';
import '../models/home_environment.dart';
import '../models/favorite_song.dart';
import '../models/live_app_alert.dart';
import '../models/voice_consent_receipt.dart';
import '../services/app_authenticated_client.dart';
import 'guardian_repository.dart';

class ApiGuardianRepository implements GuardianRepository {
  ApiGuardianRepository({
    required String baseUrl,
    this.patientId = ApiConfig.patientId,
    http.Client? client,
    String? Function()? appTokenProvider,
  }) : _baseUrl = baseUrl.replaceFirst(RegExp(r'/$'), ''),
       _client = appTokenProvider == null
           ? (client ?? http.Client())
           : AppAuthenticatedClient(
               inner: client ?? http.Client(),
               apiBaseUri: Uri.parse(baseUrl),
               tokenProvider: appTokenProvider,
             );

  static const _requestTimeout = Duration(seconds: 60);
  static const _dashboardTimeout = Duration(seconds: 75);
  static const _voiceUploadTimeout = Duration(seconds: 30);

  final String _baseUrl;
  final String patientId;
  final http.Client _client;

  @override
  Future<VoiceConsentReceipt> saveVoiceConsent({
    required String requestId,
  }) async {
    final response = await _client
        .post(
          _uri('/api/patients/$patientId/voice-training/consents'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'request_id': requestId,
            'policy_version': VoiceConsentReceipt.currentPolicyVersion,
            'accepted': true,
          }),
        )
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    final receipt = VoiceConsentReceipt.fromJson(_decodeObject(response));
    if (receipt.patientId != patientId ||
        receipt.consentId != 'voice-consent-$requestId') {
      throw const FormatException(
        'Consent receipt does not match this request',
      );
    }
    return receipt;
  }

  @override
  Future<List<FavoriteSong>> loadFavoriteSongs() async {
    final response = await _client
        .get(_uri('/api/patients/$patientId/favorite-songs'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return (_decodeObject(response)['songs'] as List<dynamic>)
        .map((item) => FavoriteSong.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  @override
  Future<List<FavoriteSong>> saveFavoriteSongs(List<FavoriteSong> songs) async {
    final response = await _client
        .put(
          _uri('/api/patients/$patientId/favorite-songs'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'songs': songs.map((song) => song.toRequestJson()).toList(),
          }),
        )
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return (_decodeObject(response)['songs'] as List<dynamic>)
        .map((item) => FavoriteSong.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  @override
  Future<HomeEnvironment> loadHomeEnvironment() async {
    final response = await _client
        .get(_uri('/api/patients/$patientId/home-environment'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return HomeEnvironment.fromJson(_decodeObject(response));
  }

  @override
  Future<HomeEnvironment> updateHomeEnvironment({
    required String regionCode,
    required bool autoLightingEnabled,
  }) async {
    final response = await _client
        .put(
          _uri('/api/patients/$patientId/home-environment'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'region_code': regionCode,
            'auto_lighting_enabled': autoLightingEnabled,
          }),
        )
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return HomeEnvironment.fromJson(_decodeObject(response));
  }

  @override
  Future<GuardianSnapshot> loadSnapshot() async {
    final response = await _client
        .get(_uri('/api/patients/$patientId/dashboard'))
        .timeout(_dashboardTimeout);
    _ensureSuccess(response);

    final payload = jsonDecode(utf8.decode(response.bodyBytes));
    return GuardianSnapshot.fromJson(payload as Map<String, dynamic>);
  }

  @override
  Future<List<LiveAppAlert>> loadAlertHistory() async {
    final response = await _client
        .get(_uri('/api/patients/$patientId/alerts'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return (_decodeObject(response)['alerts'] as List<dynamic>)
        .map((item) => LiveAppAlert.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  @override
  Future<void> markAlertRead(String alertId) async {
    final response = await _client
        .post(
          _uri(
            '/api/patients/$patientId/alerts/${Uri.encodeComponent(alertId)}/read',
          ),
        )
        .timeout(_requestTimeout);
    _ensureSuccess(response);
  }

  @override
  Future<void> pauseAlert({
    required String alertId,
    required Duration duration,
  }) async {
    final response = await _client
        .post(
          _uri('/api/patients/$patientId/repetitive-alert-pause'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'duration_minutes': duration.inMinutes}),
        )
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    final saved = _decodeObject(response);
    if (saved['scope'] != 'repetitive_behavior' ||
        saved['available'] != true ||
        saved['is_paused'] != true ||
        DateTime.tryParse(saved['paused_until'] as String? ?? '')
                ?.isAfter(DateTime.now()) !=
            true) {
      throw StateError('The server did not confirm the notification pause.');
    }
  }

  @override
  Future<void> resumeAlert({required String alertId}) async {
    final response = await _client
        .delete(_uri('/api/patients/$patientId/repetitive-alert-pause'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    final saved = _decodeObject(response);
    if (saved['scope'] != 'repetitive_behavior' ||
        saved['available'] != true ||
        saved['is_paused'] != false) {
      throw StateError('The server did not confirm resumed notifications.');
    }
  }

  @override
  Future<void> confirmDoorEvent({required String eventId}) async {
    final response = await _client
        .post(_uri('/api/door-events/$eventId/confirm'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
  }

  @override
  Future<Uint8List> loadDoorPhoto({required String eventId}) async {
    if (!RegExp(r'^[A-Za-z0-9_.:-]{1,96}$').hasMatch(eventId) ||
        eventId == '.' ||
        eventId == '..') {
      throw ArgumentError.value(eventId, 'eventId', 'Invalid door event ID');
    }

    final response = await _client
        .get(_uri('/api/door-events/${Uri.encodeComponent(eventId)}/image'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    final contentType = response.headers['content-type']
        ?.split(';')
        .first
        .trim();
    if ((contentType != 'image/jpeg' && contentType != 'image/png') ||
        response.bodyBytes.isEmpty ||
        response.bodyBytes.length > 3 * 1024 * 1024) {
      throw StateError('The server did not return a valid door photo.');
    }
    return response.bodyBytes;
  }

  @override
  Future<void> activateDemoScenario({required String scenarioId}) async {
    final response = await _client
        .post(_uri('/api/demo/scenarios/$scenarioId'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
  }

  @override
  Future<GuardianProfile> loadGuardianProfile() async {
    final response = await _client
        .get(_uri('/api/patients/$patientId/care-profile'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return GuardianProfile.fromJson(_decodeObject(response));
  }

  @override
  Future<GuardianProfile> updateGuardianProfile({
    required String name,
    required String patientName,
    required String relationship,
    required String phoneNumber,
    String? patientCallName,
  }) async {
    final response = await _client
        .put(
          _uri('/api/patients/$patientId/care-profile'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'name': name,
            'patient_name': patientName,
            'relationship': relationship,
            'phone_number': phoneNumber,
            'patient_call_name': ?patientCallName,
          }),
        )
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    final saved = GuardianProfile.fromJson(_decodeObject(response));
    if (patientCallName != null &&
        saved.patientCallName != patientCallName.trim()) {
      throw StateError('The server did not confirm the saved TTS address.');
    }
    return saved;
  }

  @override
  Future<GuardianPreferences> loadPreferences() async {
    final response = await _client
        .get(
          _uri(
            '/api/guardians/me/preferences?patient_id=${Uri.encodeQueryComponent(patientId)}',
          ),
        )
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return GuardianPreferences.fromJson(_decodeObject(response));
  }

  @override
  Future<GuardianPreferences> updatePreferences({
    required bool safetyNotifications,
    required bool soundEnabled,
  }) async {
    final response = await _client
        .put(
          _uri(
            '/api/guardians/me/preferences?patient_id=${Uri.encodeQueryComponent(patientId)}',
          ),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'safety_notifications': safetyNotifications,
            'sound_enabled': soundEnabled,
          }),
        )
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return GuardianPreferences.fromJson(_decodeObject(response));
  }

  @override
  Future<DeviceConnectionStatus> loadDeviceConnection() async {
    final response = await _client
        .get(_uri('/api/patients/$patientId/device-connection'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return DeviceConnectionStatus.fromJson(_decodeObject(response));
  }

  @override
  Future<DeviceConnectionStatus> checkDeviceConnection() async {
    final response = await _client
        .post(_uri('/api/patients/$patientId/device-connection/check'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return DeviceConnectionStatus.fromJson(_decodeObject(response));
  }

  @override
  Future<GuardianActionResult> requestCareCall() async {
    final response = await _client
        .post(_uri('/api/patients/$patientId/care-call'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return GuardianActionResult.fromJson(_decodeObject(response));
  }

  @override
  Future<GuardianActionResult> requestEmergencyContact() async {
    final response = await _client
        .post(_uri('/api/patients/$patientId/emergency-contact'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return GuardianActionResult.fromJson(_decodeObject(response));
  }

  @override
  Future<void> uploadVoiceMessage({
    required Uint8List audioBytes,
    required String fileName,
    required int durationSeconds,
  }) async {
    final request = http.MultipartRequest('POST', _uri('/api/voice-messages'))
      ..fields['patient_id'] = patientId
      ..fields['duration_seconds'] = durationSeconds.toString()
      ..files.add(
        http.MultipartFile.fromBytes('file', audioBytes, filename: fileName),
      );

    final response = await _client.send(request).timeout(_requestTimeout);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw GuardianApiException(
        statusCode: response.statusCode,
        responseBody: await response.stream.bytesToString(),
      );
    }
  }

  @override
  Future<VoiceTrainingProgress> loadVoiceTrainingProgress() async {
    final response = await _client
        .get(_uri('/api/patients/$patientId/voice-training'))
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    final payload = jsonDecode(utf8.decode(response.bodyBytes));
    return VoiceTrainingProgress.fromJson(payload as Map<String, dynamic>);
  }

  @override
  Future<VoiceTrainingProgress> startNewVoiceTraining({
    required String previousJobId,
  }) async {
    final response = await _client
        .post(
          _uri('/api/patients/$patientId/voice-training/sessions'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'previous_job_id': previousJobId}),
        )
        .timeout(_requestTimeout);
    _ensureSuccess(response);
    return VoiceTrainingProgress.fromJson(_decodeObject(response));
  }

  @override
  Future<VoiceTrainingProgress> uploadVoiceTrainingClip({
    required Uint8List audioBytes,
    required String fileName,
    required int durationSeconds,
    required String promptText,
    String? jobId,
  }) async {
    final request =
        http.MultipartRequest('POST', _uri('/api/voice-training/clips'))
          ..fields['patient_id'] = patientId
          ..fields['duration_seconds'] = durationSeconds.toString()
          ..fields['prompt_text'] = promptText
          ..files.add(
            http.MultipartFile.fromBytes(
              'file',
              audioBytes,
              filename: fileName,
            ),
          );

    if (jobId != null) request.fields['job_id'] = jobId;
    final response = await _client.send(request).timeout(_voiceUploadTimeout);
    final body = await response.stream.toBytes().timeout(_voiceUploadTimeout);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw GuardianApiException(
        statusCode: response.statusCode,
        responseBody: utf8.decode(body),
      );
    }
    final payload = jsonDecode(utf8.decode(body));
    return VoiceTrainingProgress.fromJson(payload as Map<String, dynamic>);
  }

  Uri _uri(String path) => Uri.parse('$_baseUrl$path');

  Map<String, dynamic> _decodeObject(http.Response response) {
    return jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
  }

  void _ensureSuccess(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw GuardianApiException(
        statusCode: response.statusCode,
        responseBody: utf8.decode(response.bodyBytes),
      );
    }
  }
}

class GuardianApiException implements Exception {
  const GuardianApiException({
    required this.statusCode,
    required this.responseBody,
  });

  final int statusCode;
  final String responseBody;

  @override
  String toString() => 'Guardian API error $statusCode: $responseBody';
}
