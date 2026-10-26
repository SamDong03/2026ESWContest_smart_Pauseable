import 'dart:typed_data';

import '../models/guardian_snapshot.dart';
import '../models/guardian_support.dart';
import '../models/voice_training_progress.dart';
import '../models/home_environment.dart';
import '../models/favorite_song.dart';
import '../models/live_app_alert.dart';
import '../models/voice_consent_receipt.dart';

abstract interface class GuardianRepository {
  Future<VoiceConsentReceipt> saveVoiceConsent({required String requestId});

  Future<List<FavoriteSong>> loadFavoriteSongs();

  Future<List<FavoriteSong>> saveFavoriteSongs(List<FavoriteSong> songs);

  Future<HomeEnvironment> loadHomeEnvironment();

  Future<HomeEnvironment> updateHomeEnvironment({
    required String regionCode,
    required bool autoLightingEnabled,
  });

  Future<GuardianSnapshot> loadSnapshot();

  Future<List<LiveAppAlert>> loadAlertHistory();

  Future<void> markAlertRead(String alertId);

  Future<void> pauseAlert({
    required String alertId,
    required Duration duration,
  });

  Future<void> resumeAlert({required String alertId});

  Future<void> confirmDoorEvent({required String eventId});


  Future<Uint8List> loadDoorPhoto({required String eventId});

  Future<void> activateDemoScenario({required String scenarioId});

  Future<GuardianProfile> loadGuardianProfile();

  Future<GuardianProfile> updateGuardianProfile({
    required String name,
    required String patientName,
    required String relationship,
    required String phoneNumber,
    String? patientCallName,
  });

  Future<GuardianPreferences> loadPreferences();

  Future<GuardianPreferences> updatePreferences({
    required bool safetyNotifications,
    required bool soundEnabled,
  });

  Future<DeviceConnectionStatus> loadDeviceConnection();

  Future<DeviceConnectionStatus> checkDeviceConnection();

  Future<GuardianActionResult> requestCareCall();

  Future<GuardianActionResult> requestEmergencyContact();

  Future<void> uploadVoiceMessage({
    required Uint8List audioBytes,
    required String fileName,
    required int durationSeconds,
  });

  Future<VoiceTrainingProgress> loadVoiceTrainingProgress();

  Future<VoiceTrainingProgress> startNewVoiceTraining({
    required String previousJobId,
  });

  Future<VoiceTrainingProgress> uploadVoiceTrainingClip({
    required Uint8List audioBytes,
    required String fileName,
    required int durationSeconds,
    required String promptText,
    String? jobId,
  });
}
