import 'dart:convert';

import 'package:flutter/services.dart';

import '../models/guardian_snapshot.dart';
import '../models/guardian_support.dart';
import '../models/voice_training_progress.dart';
import '../models/home_environment.dart';
import '../models/favorite_song.dart';
import '../models/live_app_alert.dart';
import '../models/voice_consent_receipt.dart';
import '../services/home_region_catalog.dart';
import 'guardian_repository.dart';

class MockGuardianRepository implements GuardianRepository {
  MockGuardianRepository();

  @override
  Future<VoiceConsentReceipt> saveVoiceConsent({
    required String requestId,
  }) async => VoiceConsentReceipt(
    consentId: 'voice-consent-$requestId',
    patientId: 'demo-patient',
    policyVersion: VoiceConsentReceipt.currentPolicyVersion,
    acceptedAt: DateTime.now().toUtc(),
  );
  HomeEnvironment _homeEnvironment = const HomeEnvironment();
  List<FavoriteSong> _favoriteSongs = [];
  GuardianProfile _profile = const GuardianProfile(
    name: '',
    relationship: '',
    phoneNumber: '',
  );

  @override
  Future<List<FavoriteSong>> loadFavoriteSongs() async =>
      List.of(_favoriteSongs);

  @override
  Future<List<FavoriteSong>> saveFavoriteSongs(List<FavoriteSong> songs) async {
    _favoriteSongs = List.of(songs);
    return List.of(_favoriteSongs);
  }

  @override
  Future<HomeEnvironment> loadHomeEnvironment() async => _homeEnvironment;

  @override
  Future<HomeEnvironment> updateHomeEnvironment({
    required String regionCode,
    required bool autoLightingEnabled,
  }) async {
    final regions = await HomeRegionCatalog.load();
    return _homeEnvironment = HomeEnvironment(
      region: regions.firstWhere((r) => r.code == regionCode),
      autoLightingEnabled: autoLightingEnabled,
      lightingStatus: autoLightingEnabled ? 'awaiting_integration' : 'disabled',
    );
  }

  @override
  Future<GuardianSnapshot> loadSnapshot() async {
    final source = await rootBundle.loadString(
      'assets/mock/guardian_snapshot.json',
    );
    final json = jsonDecode(source) as Map<String, dynamic>;

    return GuardianSnapshot.fromJson(json);
  }

  @override
  Future<List<LiveAppAlert>> loadAlertHistory() async => const [];

  @override
  Future<void> markAlertRead(String alertId) async {}

  @override
  Future<void> pauseAlert({
    required String alertId,
    required Duration duration,
  }) async {}

  @override
  Future<void> resumeAlert({required String alertId}) async {}

  @override
  Future<void> confirmDoorEvent({required String eventId}) async {}

  @override
  Future<Uint8List> loadDoorPhoto({required String eventId}) async {
    final snapshot = await loadSnapshot();
    final event = snapshot.doorEvents.firstWhere(
      (event) => event.id == eventId,
    );
    if (!event.imageUrl.startsWith('asset://')) {
      throw StateError('Demo photos must be bundled assets.');
    }
    final bytes = await rootBundle.load(
      event.imageUrl.substring('asset://'.length),
    );
    return bytes.buffer.asUint8List(bytes.offsetInBytes, bytes.lengthInBytes);
  }

  @override
  Future<void> activateDemoScenario({required String scenarioId}) async {}

  @override
  Future<GuardianProfile> loadGuardianProfile() async => _profile;

  @override
  Future<GuardianProfile> updateGuardianProfile({
    required String name,
    required String patientName,
    required String relationship,
    required String phoneNumber,
    String? patientCallName,
  }) async => _profile = GuardianProfile(
    name: name,
    patientName: patientName,
    relationship: relationship,
    phoneNumber: phoneNumber,
    patientCallName: patientCallName ?? _profile.patientCallName,
  );

  @override
  Future<GuardianPreferences> loadPreferences() async =>
      const GuardianPreferences(safetyNotifications: true, soundEnabled: false);

  @override
  Future<GuardianPreferences> updatePreferences({
    required bool safetyNotifications,
    required bool soundEnabled,
  }) async => GuardianPreferences(
    safetyNotifications: safetyNotifications,
    soundEnabled: soundEnabled,
  );

  @override
  Future<DeviceConnectionStatus> loadDeviceConnection() async =>
      _demoDeviceConnection;

  @override
  Future<DeviceConnectionStatus> checkDeviceConnection() async =>
      _demoDeviceConnection;

  @override
  Future<GuardianActionResult> requestCareCall() async =>
      const GuardianActionResult(
        title: '보호 전화 요청 완료',
        message: '대상자에게 보호 전화를 연결하는 가상 요청을 보냈습니다.',
        referenceId: 'demo-care-call-001',
      );

  @override
  Future<GuardianActionResult> requestEmergencyContact() async =>
      const GuardianActionResult(
        title: '긴급 연락 요청 완료',
        message: '등록된 보호자와 긴급 연락망에 가상 요청을 보냈습니다.',
        referenceId: 'demo-emergency-001',
      );

  @override
  Future<void> uploadVoiceMessage({
    required Uint8List audioBytes,
    required String fileName,
    required int durationSeconds,
  }) async {}

  @override
  Future<VoiceTrainingProgress> loadVoiceTrainingProgress() async =>
      _voiceProgress;

  VoiceTrainingProgress _voiceProgress = const VoiceTrainingProgress.empty();
  int _voiceSession = 1;
  String? _previousVoiceJob;

  @override
  Future<VoiceTrainingProgress> startNewVoiceTraining({
    required String previousJobId,
  }) async {
    if (_previousVoiceJob == previousJobId) return _voiceProgress;
    if (!_voiceProgress.canStartNewTraining ||
        _voiceProgress.jobId != previousJobId) {
      throw StateError('현재 음성 학습이 완료된 뒤 다시 시작해 주세요.');
    }
    _previousVoiceJob = previousJobId;
    _voiceSession++;
    return _voiceProgress = VoiceTrainingProgress(
      targetSeconds: 800,
      recordedSeconds: 0,
      clipCount: 0,
      isReady: false,
      jobId: 'voice-job-${_voiceSession.toRadixString(16).padLeft(12, '0')}',
    );
  }

  @override
  Future<VoiceTrainingProgress> uploadVoiceTrainingClip({
    required Uint8List audioBytes,
    required String fileName,
    required int durationSeconds,
    required String promptText,
    String? jobId,
  }) async {
    if (!_voiceProgress.canRecord ||
        (jobId != null && jobId != _voiceProgress.jobId)) {
      throw StateError('음성 학습 세트를 다시 확인해 주세요.');
    }
    final seconds = _voiceProgress.recordedSeconds + durationSeconds;
    final count = _voiceProgress.clipCount + 1;
    return _voiceProgress = VoiceTrainingProgress(
      targetSeconds: 800,
      recordedSeconds: seconds,
      clipCount: count,
      isReady: seconds >= 800,
      jobId: _voiceProgress.jobId ?? 'voice-job-000000000001',
      jobStatus: count >= 160 ? 'completed' : 'collecting',
    );
  }
}

const _demoDeviceConnection = DeviceConnectionStatus(
  deviceName: 'PAUSEABLE Home',
  isOnline: true,
  lastCheckedLabel: '방금 전',
  services: [
    DeviceServiceStatus(
      name: 'Home Assistant',
      isConnected: true,
      detail: '가상 센서 데이터 수신 중',
    ),
    DeviceServiceStatus(
      name: '현관 센서·카메라',
      isConnected: true,
      detail: '가상 출입 이벤트 사용 중',
    ),
    DeviceServiceStatus(
      name: 'Raspberry Pi 5',
      isConnected: true,
      detail: '가상 연결 상태',
    ),
  ],
);
